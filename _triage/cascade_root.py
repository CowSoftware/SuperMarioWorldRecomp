"""Option A cascade-root finder.

Anchors recomp + snes9x at the same logical event (GameMode==0x07
transition: level loaded). Then walks logical frames forward, dumping
the FULL 128KB WRAM on both sides at each k = 0..N, and finds:

  1. The FIRST k where any byte of WRAM differs between the two sides.
  2. The first (lowest) divergent address at that k.
  3. A surrounding window for context.

That tuple (k, addr, rec_byte, emu_byte) is the cascade-root signal:
the upstream codegen-affected byte that the rest of the divergence
flows from.

Pre-conditions:
  * Oracle build with the extended 3000-frame × 128KB emu ring.
  * Both sides receive the same demo input plumbing per
    emu_oracle_run_frame (already wired in main.c).

Post-attach budget:
  * snes9x's per-frame ring holds 3000 frames; anchor at frame
    ~1000-2000 typically survives until cascade scan completes.
  * If the anchor is evicted (probe started too late), report and
    bail — Option A's reset/RNG injection would be the next step,
    but for now boot fast.
"""
from __future__ import annotations
import argparse, json, pathlib, socket, subprocess, sys, time

REPO = pathlib.Path(__file__).parent.parent
EXE = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'
PORT = 4377

GAME_MODE_ADDR = 0x0100
DEFAULT_TARGET_GM = 0x07


def _kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())


def find_recomp_anchor_frame(sock, f, target_val):
    h = cmd(sock, f, 'history').get('history', {})
    oldest = h.get('oldest', -1); newest = h.get('newest', -1)
    if oldest < 0 or newest < 0:
        return None
    fr = oldest
    while fr <= newest:
        end = min(fr + 499, newest)
        r = cmd(sock, f, f'frame_range {fr} {end}')
        for frec in r.get('frames', []):
            mode_hex = frec.get('mode', '0x00')
            try:
                mode = int(mode_hex, 0) if isinstance(mode_hex, str) else mode_hex
            except (ValueError, TypeError):
                continue
            if mode == target_val:
                return frec.get('f')
        fr = end + 1
    return None


def find_emu_anchor_frame(sock, f, target_val):
    h = cmd(sock, f, 'emu_history')
    oldest = h.get('oldest', -1); newest = h.get('newest', -1)
    if oldest < 0 or newest < 0:
        return None
    # Linear scan; emu_wram_at_frame is per-byte but cheap (single
    # RTT) so 3000 iterations finishes in ~1s on localhost.
    for fr in range(oldest, newest + 1):
        r = cmd(sock, f, f'emu_wram_at_frame {fr} {GAME_MODE_ADDR:x}')
        try:
            v = int(r.get('val', '0x0'), 0)
        except (ValueError, TypeError):
            continue
        if v == target_val:
            return fr
    return None


def dump_full_wram(sock, f, side, frame):
    """Returns 128KB bytes or None on miss."""
    if side == 'rec':
        cmd_str = f'dump_frame_wram {frame} 0 131072'
    else:
        cmd_str = f'emu_dump_frame_wram {frame} 0 131072'
    r = cmd(sock, f, cmd_str)
    hex_str = r.get('hex')
    if hex_str is None or len(hex_str) != 0x40000:  # 128KB × 2 chars
        return None
    return bytes.fromhex(hex_str)


# Architectural-noise mask — these regions diverge for reasons that are
# NOT codegen bugs and would otherwise drown out real signals:
#
#   $7E:0100-01FF (page 1, SNES stack)
#     Recomp uses the host C stack for PHA/PHX/PHY/PHP/JSR/RTS, so
#     g_ram[$0100-$01FF] is never touched. Snes9x emulates the SNES
#     stack at $7E:01XX. Any post-frame snapshot has differing values
#     wherever the stack reached, with the rec side reading 0x00.
#
# This mask is ARCHITECTURAL, not a "skip this bug." Adding a region
# here is a claim that the underlying difference reflects a known and
# legitimate runtime divergence between recomp and snes9x.
DEFAULT_MASK = [
    (0x0100, 0x01FF),   # page 1 = SNES stack
]


def is_masked(addr, mask):
    for lo, hi in mask:
        if lo <= addr <= hi:
            return True
    return False


def first_divergence(rec_w, emu_w, mask=None):
    """Returns (addr, rec_byte, emu_byte) for the lowest differing
    non-masked byte, or None if all-equal modulo the mask. Quick
    equality check first for the common case."""
    if mask is None and rec_w == emu_w:
        return None
    for i in range(len(rec_w)):
        if rec_w[i] != emu_w[i]:
            if mask and is_masked(i, mask):
                continue
            return (i, rec_w[i], emu_w[i])
    return None


def all_divergent_addrs(rec_w, emu_w, mask=None, limit=64):
    out = []
    for i in range(len(rec_w)):
        if rec_w[i] != emu_w[i]:
            if mask and is_masked(i, mask):
                continue
            out.append((i, rec_w[i], emu_w[i]))
            if len(out) >= limit:
                break
    return out


def count_divergent(rec_w, emu_w, mask=None):
    n = 0
    for i in range(len(rec_w)):
        if rec_w[i] != emu_w[i]:
            if mask and is_masked(i, mask):
                continue
            n += 1
    return n


def divergent_addr_set(rec_w, emu_w, mask=None):
    out = set()
    for i in range(len(rec_w)):
        if rec_w[i] != emu_w[i]:
            if mask and is_masked(i, mask):
                continue
            out.add(i)
    return out


def coalesce_addrs(addrs, gap=8):
    """Sort and coalesce a set of byte addresses into runs."""
    if not addrs:
        return []
    sorted_a = sorted(addrs)
    runs = []
    cur_lo = sorted_a[0]; cur_hi = sorted_a[0]
    for a in sorted_a[1:]:
        if a - cur_hi <= gap:
            cur_hi = a
        else:
            runs.append((cur_lo, cur_hi))
            cur_lo = a; cur_hi = a
    runs.append((cur_lo, cur_hi))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-gm', type=lambda s: int(s, 0),
                    default=DEFAULT_TARGET_GM,
                    help='GameMode value to anchor on (default 0x07 = level running)')
    ap.add_argument('--max-k', type=int, default=600,
                    help='max logical frames forward from anchor to scan (default 600)')
    ap.add_argument('--boot-wait', type=float, default=8.0,
                    help='seconds to wait after launch for demo to reach anchor')
    ap.add_argument('--no-mask', action='store_true',
                    help='disable architectural-noise mask (debug)')
    args = ap.parse_args()
    mask = None if args.no_mask else DEFAULT_MASK

    _kill(); time.sleep(0.5)
    proc = subprocess.Popen([str(EXE)], cwd=str(REPO),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        sock = socket.socket()
        for _ in range(60):
            try:
                sock.connect(('127.0.0.1', PORT)); break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.2)
        f = sock.makefile('r')
        f.readline()
        time.sleep(args.boot_wait)

        rec_anchor = find_recomp_anchor_frame(sock, f, args.target_gm)
        emu_anchor = find_emu_anchor_frame(sock, f, args.target_gm)
        print(f'rec_anchor (first frame GM=0x{args.target_gm:02x}): {rec_anchor}')
        print(f'emu_anchor (first frame GM=0x{args.target_gm:02x}): {emu_anchor}')
        if rec_anchor is None or emu_anchor is None:
            print('FAIL: anchor not found in either ring (boot-wait too short, or ring evicted).')
            return 1

        rec_h = cmd(sock, f, 'history').get('history', {})
        emu_h = cmd(sock, f, 'emu_history')
        print(f'rec ring: oldest={rec_h.get("oldest")}, newest={rec_h.get("newest")}')
        print(f'emu ring: oldest={emu_h.get("oldest")}, newest={emu_h.get("newest")}')

        rec_max = rec_h.get('newest', rec_anchor)
        emu_max = emu_h.get('newest', emu_anchor)
        scan_end = min(args.max_k, rec_max - rec_anchor, emu_max - emu_anchor)
        print(f'\nscanning k = 0..{scan_end} ...')

        # Walk every k. Track per-byte first-divergence frame. A byte
        # is "newly diverging" at k if the byte was equal at every
        # prior k and differs at k. That's the cascade-root signal at
        # byte granularity, immune to coalescing artifacts.
        first_diverge_at = {}      # addr -> k of first divergence
        ever_diverged = set()
        anchor_count = None
        anchor_runs = None
        t0 = time.time()
        last_heartbeat_k = -1

        for k in range(0, scan_end + 1):
            rec_w = dump_full_wram(sock, f, 'rec', rec_anchor + k)
            emu_w = dump_full_wram(sock, f, 'emu', emu_anchor + k)
            if rec_w is None:
                print(f'  k={k}: rec_frame={rec_anchor + k} EVICTED — partial result.')
                break
            if emu_w is None:
                print(f'  k={k}: emu_frame={emu_anchor + k} EVICTED — partial result.')
                break

            divergent_now = divergent_addr_set(rec_w, emu_w, mask=mask)
            new_addrs = divergent_now - ever_diverged
            for a in new_addrs:
                first_diverge_at[a] = k
            ever_diverged |= divergent_now

            if k == 0:
                anchor_count = len(divergent_now)
                anchor_runs = coalesce_addrs(divergent_now)
                elapsed = time.time() - t0
                print(f'\n  k=0 anchor baseline: '
                      f'divergent_bytes={anchor_count} in {len(anchor_runs)} runs '
                      f'(elapsed={elapsed:.1f}s)')
                for lo, hi in anchor_runs[:30]:
                    bank = '7E' if lo < 0x10000 else '7F'
                    lo_off = lo if lo < 0x10000 else lo - 0x10000
                    hi_off = hi if hi < 0x10000 else hi - 0x10000
                    n = sum(1 for x in range(lo, hi+1) if x in divergent_now)
                    print(f'    [base] ${bank}:{lo_off:04x}-${bank}:{hi_off:04x}  '
                          f'len={hi-lo+1} ndiff={n}')
                last_heartbeat_k = 0
                continue

            # Periodic heartbeat — non-zero new bytes at this k counts
            # the cascade growth. Print every k if growth, otherwise
            # heartbeat every 50k.
            if new_addrs:
                if k - last_heartbeat_k >= 5 or len(new_addrs) > 8:
                    elapsed = time.time() - t0
                    new_runs = coalesce_addrs(new_addrs)
                    print(f'  k={k}: +{len(new_addrs)} new divergent bytes '
                          f'in {len(new_runs)} runs '
                          f'(total ever-divergent={len(ever_diverged)}, '
                          f'rec_frame={rec_anchor + k}, elapsed={elapsed:.1f}s)')
                    for lo, hi in new_runs[:8]:
                        bank = '7E' if lo < 0x10000 else '7F'
                        lo_off = lo if lo < 0x10000 else lo - 0x10000
                        hi_off = hi if hi < 0x10000 else hi - 0x10000
                        n = sum(1 for x in range(lo, hi+1) if x in new_addrs)
                        print(f'      [NEW] ${bank}:{lo_off:04x}-${bank}:{hi_off:04x}  '
                              f'len={hi-lo+1} ndiff={n}  '
                              f'rec=0x{rec_w[lo]:02x} emu=0x{emu_w[lo]:02x}')
                    last_heartbeat_k = k
            elif k - last_heartbeat_k >= 50:
                elapsed = time.time() - t0
                print(f'  k={k}: no new divergences '
                      f'(total ever-divergent={len(ever_diverged)}, elapsed={elapsed:.1f}s)')
                last_heartbeat_k = k

        elapsed = time.time() - t0
        print(f'\nscan complete: {scan_end+1} frames in {elapsed:.1f}s')
        print(f'  k=0 anchor baseline: {anchor_count} divergent bytes')
        print(f'  total ever-divergent across scan: {len(ever_diverged)} bytes')

        # Emit a histogram: for each k, how many addrs first diverged.
        per_k_counts = {}
        for a, k in first_diverge_at.items():
            per_k_counts[k] = per_k_counts.get(k, 0) + 1
        print(f'\nFirst-divergence histogram (top 30 k by new-byte count):')
        ranked = sorted(per_k_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for k, n in ranked[:30]:
            rec_fr = rec_anchor + k
            print(f'  k={k:3d} (rec_frame={rec_fr}): {n} bytes first diverged here')
        return 0
    finally:
        try: sock.close()
        except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        _kill()


if __name__ == '__main__':
    sys.exit(main())
