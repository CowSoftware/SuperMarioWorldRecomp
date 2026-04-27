"""Ring-driven recomp-vs-snes9x divergence differ.

Both rings (recomp's RDB_BLOCK_HOOK and snes9x's per-insn trace) are
ALWAYS-ON in the Oracle build. This tool free-runs the runtime, waits
for the window of interest to materialize in both rings, then queries
the rings backward in history. NO pause+step+emu_step lockstep.

Sync model:
    1. Free-run the runtime (no --paused).
    2. Wait until both sides have enough recorded history for the
       chosen anchor PC to appear at least once.
    3. Pull both rings (filtered by --pc-lo / --pc-hi).
    4. Find the first occurrence of --anchor-pc in BOTH rings; mark
       cursors. (Without --anchor-pc, sync at the first PC the two
       rings share.)
    5. From those cursors, walk forward and diff.

Usage:
    python tools/oracle_block_diff.py [--anchor-pc HEX] [--pc-lo HEX]
        [--pc-hi HEX] [--max-divergences N] [--wait-seconds N]

A divergence is reported with both ring indices (`rec_idx`, `emu_idx`)
and the snes_frame / s_watch_frame counters at that moment, so a
follow-up probe can re-query the same window directly.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import socket
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
ORACLE_EXE = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'
PORT = 4377

# RDB_REG_UNKNOWN sentinel emitted by recomp's symbolic tracker.
REG_UNKNOWN = 0xFFFFFFFF


def _kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)


def _launch_free_running():
    """Launch the Oracle build WITHOUT --paused. Both rings are
    always-on, so they start filling immediately and we read them
    back without ever pausing the runtime."""
    if not ORACLE_EXE.exists():
        sys.exit(f'Oracle binary not found: {ORACLE_EXE}')
    _kill()
    time.sleep(0.5)
    p = subprocess.Popen(
        [str(ORACLE_EXE)], cwd=str(REPO),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            s = socket.create_connection(('127.0.0.1', PORT), timeout=0.3)
            s.settimeout(None)
            return p, s
        except (OSError, ConnectionRefusedError):
            time.sleep(0.2)
    p.kill()
    sys.exit('Oracle TCP server never came up')


def _cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())


def _pull_block_trace(sock, f, pc_lo: int, pc_hi: int):
    """Pull the recomp block ring filtered by PC range.

    Uses the handler's index-based pagination (idx_from=, idx_lim=),
    distinct from the legacy from=/to= frame-range filter. The handler
    returns next_idx so we can resume cleanly even when the JSON
    buffer truncates the response well before idx_lim.
    """
    out = []
    chunk = 4096
    idx_from = 0
    while True:
        r = _cmd(sock, f,
                 f'get_block_trace idx_from={idx_from} idx_lim={chunk} '
                 f'pc_lo=0x{pc_lo:x} pc_hi=0x{pc_hi:x}')
        log = r.get('log', [])
        if log:
            out.extend(log)
        next_idx = r.get('next_idx', idx_from)
        total = r.get('total', 0)
        if next_idx <= idx_from:
            break
        idx_from = next_idx
        if total and idx_from >= total:
            break
    return out


def _pull_insn_trace(sock, f, pc_lo: int, pc_hi: int):
    """Pull the snes9x per-insn ring filtered by PC range.

    Same JSON-buffer truncation as _pull_block_trace — drive by the
    raw `i` index returned in each entry, and stop once the C side's
    `total` shows we've passed the live count.
    """
    out = []
    chunk = 4096
    from_idx = 0
    last_advance = -1
    while True:
        r = _cmd(sock, f,
                 f'emu_get_insn_trace from={from_idx} limit={chunk} '
                 f'pc_lo=0x{pc_lo:x} pc_hi=0x{pc_hi:x}')
        log = r.get('log', [])
        total = r.get('total', 0)
        if not log:
            break
        out.extend(log)
        next_from = log[-1]['i'] + 1
        if next_from <= last_advance:
            break
        last_advance = next_from
        if total and next_from >= total:
            break
        from_idx = next_from
    return out


def _wait_until_anchor_visible(sock, f, anchor_pc: int | None,
                               wait_seconds: float, pc_lo: int, pc_hi: int):
    """Free-running runtime: poll until either both rings contain the
    anchor PC (if specified) or wait_seconds elapses (if not). Returns
    the elapsed wall-clock time."""
    t0 = time.time()
    deadline = t0 + wait_seconds
    while time.time() < deadline:
        if anchor_pc is None:
            time.sleep(min(0.5, deadline - time.time()))
            continue
        # Sample tail of each ring cheaply: ask for the last 64 entries
        # and search them. If the anchor isn't there, sleep briefly and
        # retry. This is a poll on free-running data; it never pauses
        # or steps the runtime.
        rec = _cmd(sock, f,
                   f'get_block_trace from=0 limit=4096 '
                   f'pc_lo=0x{anchor_pc:x} pc_hi=0x{anchor_pc:x}')
        emu = _cmd(sock, f,
                   f'emu_get_insn_trace from=0 limit=4096 '
                   f'pc_lo=0x{anchor_pc:x} pc_hi=0x{anchor_pc:x}')
        if rec.get('log') and emu.get('log'):
            return time.time() - t0
        time.sleep(0.1)
    return time.time() - t0


def _find_anchor_index(entries, anchor_pc: int):
    for i, e in enumerate(entries):
        if int(e['pc'], 0) == anchor_pc:
            return i
    return -1


def _diff_streams(rec_blocks, emu_insns,
                  rec_anchor: int, emu_anchor: int,
                  max_divergences: int):
    """Walk rec_blocks from rec_anchor. For each, find the next
    occurrence of the same PC in emu_insns (>= current cursor). The
    naive while-loop search is O(N*M) when sparse-vs-dense mismatches
    cascade not-found rollbacks; a PC->sorted-indices index converts
    the inner search to O(log N) bisect.

    Compare (A, X, Y) at the matched PC."""
    import bisect
    divergences = []
    n_emu = len(emu_insns)

    # Pre-parse PC ints (hex strings are expensive to int() repeatedly)
    # and build PC -> sorted insn indices for >= cursor lookup.
    emu_pcs = [int(e['pc'], 0) for e in emu_insns]
    pc_index: dict[int, list[int]] = {}
    for i, pc in enumerate(emu_pcs):
        pc_index.setdefault(pc, []).append(i)

    j_min = emu_anchor
    compared = skipped_unknown = not_found = 0

    def _rec_reg(v):
        if v is None or v == '?' or v == REG_UNKNOWN:
            return None
        if isinstance(v, str):
            return int(v, 0)
        return v

    for ri in range(rec_anchor, len(rec_blocks)):
        rblk = rec_blocks[ri]
        rec_pc = int(rblk['pc'], 0)
        idx_list = pc_index.get(rec_pc)
        if not idx_list:
            not_found += 1
            continue
        # First insn index >= j_min for this PC.
        k = bisect.bisect_left(idx_list, j_min)
        if k >= len(idx_list):
            not_found += 1
            continue
        j = idx_list[k]
        emu = emu_insns[j]
        # Advance the cursor past this match so the next rec_block
        # search begins after it. Linear-time across the whole walk.
        j_min = j + 1

        rec_a = _rec_reg(rblk.get('a'))
        rec_x = _rec_reg(rblk.get('x'))
        rec_y = _rec_reg(rblk.get('y'))

        emu_a = int(emu['a'], 0)
        emu_x = int(emu['x'], 0)
        emu_y = int(emu['y'], 0)
        m  = emu.get('m', 0)
        xf = emu.get('x_flag', 0)
        emu_a_cmp = (emu_a & 0xFF) if m  else (emu_a & 0xFFFF)
        emu_x_cmp = (emu_x & 0xFF) if xf else (emu_x & 0xFFFF)
        emu_y_cmp = (emu_y & 0xFF) if xf else (emu_y & 0xFFFF)

        diffs = []
        for name, rv, ev in (('A', rec_a, emu_a_cmp),
                             ('X', rec_x, emu_x_cmp),
                             ('Y', rec_y, emu_y_cmp)):
            if rv is None: continue
            if rv != ev:   diffs.append((name, rv, ev))

        if all(rv is None for rv in (rec_a, rec_x, rec_y)):
            skipped_unknown += 1
            continue
        compared += 1

        if diffs:
            divergences.append({
                'rec_idx': ri, 'emu_idx': emu['i'],
                'pc': f'0x{rec_pc:06x}',
                'frame_rec': rblk.get('f'), 'frame_emu': emu.get('f'),
                'diffs': diffs,
                'rec_avx': (rec_a, rec_x, rec_y),
                'emu_avx': (emu_a_cmp, emu_x_cmp, emu_y_cmp),
                'm': m, 'x_flag': xf,
            })
            if len(divergences) >= max_divergences:
                break

    return divergences, {
        'compared': compared,
        'skipped_unknown': skipped_unknown,
        'not_found_in_oracle': not_found,
        'rec_blocks_total': len(rec_blocks),
        'emu_insns_total': len(emu_insns),
        'rec_anchor': rec_anchor,
        'emu_anchor': emu_anchor,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pc-lo', type=lambda s: int(s, 0), default=0,
                    help='lower 24-bit PC bound for both ring queries')
    ap.add_argument('--pc-hi', type=lambda s: int(s, 0), default=0xFFFFFF,
                    help='upper 24-bit PC bound for both ring queries')
    ap.add_argument('--anchor-pc', type=lambda s: int(s, 0), default=None,
                    help='24-bit PC that must appear in BOTH rings; '
                         'walk forward from its first occurrence in each. '
                         'If omitted, syncs at the first PC the two rings '
                         'share within the pc range.')
    ap.add_argument('--wait-seconds', type=float, default=10.0,
                    help='how long to let the runtime free-run before '
                         'querying the rings (default 10s)')
    ap.add_argument('--max-divergences', type=int, default=20)
    args = ap.parse_args()

    proc, sock = _launch_free_running()
    f = sock.makefile('r')
    f.readline()  # banner
    try:
        if args.anchor_pc is not None:
            print(f'[diff] free-running runtime; waiting up to '
                  f'{args.wait_seconds}s for anchor 0x{args.anchor_pc:06x} '
                  f'to appear in BOTH rings...')
        else:
            print(f'[diff] free-running runtime for {args.wait_seconds}s '
                  f'to populate both rings...')
        elapsed = _wait_until_anchor_visible(
            sock, f, args.anchor_pc, args.wait_seconds,
            args.pc_lo, args.pc_hi)
        print(f'[diff] window populated after {elapsed:.2f}s wall-clock')

        print(f'[diff] pulling rings (pc {args.pc_lo:#x}..{args.pc_hi:#x})...')
        rec_blocks = _pull_block_trace(sock, f, args.pc_lo, args.pc_hi)
        emu_insns  = _pull_insn_trace(sock, f, args.pc_lo, args.pc_hi)
        print(f'[diff] rec block entries: {len(rec_blocks)}')
        print(f'[diff] emu insn entries:  {len(emu_insns)}')

        if not rec_blocks or not emu_insns:
            print('[diff] one or both rings empty in the requested PC '
                  'range — nothing to diff. Try a wider --pc-lo/--pc-hi '
                  'or longer --wait-seconds.', file=sys.stderr)
            return

        if args.anchor_pc is not None:
            rec_anchor = _find_anchor_index(rec_blocks, args.anchor_pc)
            emu_anchor = _find_anchor_index(emu_insns,  args.anchor_pc)
            if rec_anchor < 0 or emu_anchor < 0:
                print(f'[diff] anchor 0x{args.anchor_pc:06x} not found '
                      f'(rec={rec_anchor}, emu={emu_anchor}). Either let '
                      f'the runtime run longer (--wait-seconds) or pick a '
                      f'PC that both sides hit.', file=sys.stderr)
                return
        else:
            # Default: sync at the first PC both rings contain.
            emu_pcs = {int(e['pc'], 0) for e in emu_insns}
            rec_anchor = next((i for i, e in enumerate(rec_blocks)
                               if int(e['pc'], 0) in emu_pcs), -1)
            if rec_anchor < 0:
                print('[diff] no shared PC between rings in the requested '
                      'range', file=sys.stderr)
                return
            shared_pc = int(rec_blocks[rec_anchor]['pc'], 0)
            emu_anchor = _find_anchor_index(emu_insns, shared_pc)
            print(f'[diff] auto-anchor at PC 0x{shared_pc:06x} '
                  f'(rec_idx={rec_anchor}, emu_idx={emu_anchor})')

        divs, stats = _diff_streams(rec_blocks, emu_insns,
                                    rec_anchor, emu_anchor,
                                    args.max_divergences)
        print()
        print(f'[diff] anchor: rec_idx={stats["rec_anchor"]} '
              f'emu_idx={stats["emu_anchor"]}')
        print(f'[diff] compared={stats["compared"]} '
              f'skipped_unknown={stats["skipped_unknown"]} '
              f'not_found={stats["not_found_in_oracle"]}')
        print(f'[diff] divergences: {len(divs)}')
        for d in divs:
            diffs_str = ' '.join(
                f'{n}: rec=0x{rv:x} emu=0x{ev:x}'
                for n, rv, ev in d['diffs'])
            print(f'  rec_idx={d["rec_idx"]:6d} emu_idx={d["emu_idx"]:7d} '
                  f'pc={d["pc"]} frame_rec={d["frame_rec"]} '
                  f'frame_emu={d["frame_emu"]}  {diffs_str}')
    finally:
        try: sock.close()
        except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        _kill()


if __name__ == '__main__':
    main()
