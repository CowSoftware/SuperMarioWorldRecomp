"""Golden-oracle probe for Mario-falls-one-below-?-block.

Symptom: Mario jumps near the yoshi-?-block, lands beside it, falls
one tile into solid ground. The tile he should land on is missing
or mis-classified as air.

Hypothesis: my diagonal-ledge fix still has an off-by-one in tile-
generation (snes9x produces 309 writes to $0F during level load;
post-fix produces 259 — 50 missing writes). One of those missing
writes IS the platform tile under Mario's landing position.

Probe: anchor at GameMode=0x14 (level fully running; post-load,
post-Map16-expansion). Diff Map16 high-byte buffer ($C800-$FFFF)
and level-tile-state region between recomp and snes9x. Any byte
that differs is a Map16 tile that recomp generated wrong.
"""
from __future__ import annotations
import json, pathlib, socket, subprocess, time

REPO = pathlib.Path(__file__).parent.parent
EXE = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'
PORT = 4377

GAME_MODE_ADDR = 0x0100


def _kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())


def find_recomp_anchor(sock, f, target):
    h = cmd(sock, f, 'history').get('history', {})
    oldest, newest = h.get('oldest', -1), h.get('newest', -1)
    if oldest < 0:
        return None
    fr = oldest
    while fr <= newest:
        end = min(fr + 499, newest)
        r = cmd(sock, f, f'frame_range {fr} {end}')
        for frec in r.get('frames', []):
            mh = frec.get('mode', '0x00')
            try:
                m = int(mh, 0) if isinstance(mh, str) else mh
            except (ValueError, TypeError):
                continue
            if m == target:
                return frec.get('f')
        fr = end + 1
    return None


def find_emu_anchor(sock, f, addr, target):
    h = cmd(sock, f, 'emu_history')
    oldest, newest = h.get('oldest', -1), h.get('newest', -1)
    if oldest < 0:
        return None
    for fr in range(oldest, newest + 1):
        r = cmd(sock, f, f'emu_wram_at_frame {fr} {addr:x}')
        v = r.get('val', '0')
        try:
            if int(v, 0) == target:
                return fr
        except (ValueError, TypeError):
            continue
    return None


def diff_region(sock, f, rec_anchor, emu_anchor, lo, hi, label, max_show=20):
    """Diff a WRAM byte range. recomp side via dump_frame_wram (bulk
    hex), snes9x side via emu_wram_at_frame (byte at a time — slow but
    works). For large ranges we sample first."""
    width = hi - lo
    print(f'\n  {label} (${lo:05x}-${hi-1:05x}, {width} bytes):')
    rec_w = cmd(sock, f, f'dump_frame_wram {rec_anchor} {lo:x} {width}').get(
        'hex', '').replace(' ', '')
    if not rec_w or len(rec_w) < width * 2:
        print(f'    recomp WRAM dump truncated ({len(rec_w)} chars)')
        return
    # Sample emu side: query every byte (slow). For first pass, sample
    # every 16th byte to find HOT regions, then drill in.
    diffs = []
    step = max(1, width // 1024)  # cap at ~1024 emu queries
    for off_in_range in range(0, width, step):
        addr = lo + off_in_range
        r = cmd(sock, f, f'emu_wram_at_frame {emu_anchor} {addr:x}')
        ev = r.get('val', '0')
        try:
            emu = int(ev, 0) if isinstance(ev, str) else ev
        except (ValueError, TypeError):
            emu = 0
        rec = int(rec_w[off_in_range*2:off_in_range*2+2], 16)
        if rec != emu:
            diffs.append((addr, rec, emu))
    print(f'    sampled {(width+step-1)//step} bytes (every {step}th); '
          f'{len(diffs)} diffs found')
    for addr, r, e in diffs[:max_show]:
        print(f'    $7E:{addr:05x}: rec=0x{r:02x} emu=0x{e:02x}')
    return len(diffs)


def main():
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
        # Run long enough for attract demo to enter the level. GameMode
        # 0x14 is "level normal running"; 0x07 is level-load complete.
        # Try 0x14 first; fall back to 0x07 if 0x14 not reached.
        time.sleep(15.0)
        # First diagnostic: dump GameMode trajectory on both sides.
        h = cmd(sock, f, 'history').get('history', {})
        ro, rn = h.get('oldest', -1), h.get('newest', -1)
        print(f'rec history: {ro}..{rn}')
        eh = cmd(sock, f, 'emu_history')
        eo, en = eh.get('oldest', -1), eh.get('newest', -1)
        print(f'emu history: {eo}..{en}')
        # Show distinct GameMode values seen on each side.
        rec_modes_seen = set()
        for fr in range(ro, rn + 1, 50):
            rb = cmd(sock, f, f'frame_range {fr} {fr}').get('frames', [])
            if rb:
                rec_modes_seen.add(rb[0].get('mode'))
        print(f'rec GameMode values seen: {sorted(rec_modes_seen)}')
        emu_modes_seen = set()
        for fr in range(eo, en + 1, 50):
            r = cmd(sock, f, f'emu_wram_at_frame {fr} {GAME_MODE_ADDR:x}')
            emu_modes_seen.add(r.get('val'))
        print(f'emu GameMode values seen: {sorted(emu_modes_seen)}')
        # Pick the deepest mode both sides reach.
        target = 0x14
        rec_anchor = find_recomp_anchor(sock, f, target)
        emu_anchor = find_emu_anchor(sock, f, GAME_MODE_ADDR, target)
        if rec_anchor is None or emu_anchor is None:
            print(f'GameMode 0x14 not reached; trying 0x07')
            target = 0x07
            rec_anchor = find_recomp_anchor(sock, f, target)
            emu_anchor = find_emu_anchor(sock, f, GAME_MODE_ADDR, target)
        print(f'rec anchor (GameMode=0x{target:02x}): {rec_anchor}')
        print(f'emu anchor (GameMode=0x{target:02x}): {emu_anchor}')
        if rec_anchor is None or emu_anchor is None:
            return

        # Map16 buffers in SMW WRAM:
        #   Map16 low byte buffer:  $7E:C800-$7EFFFF (14336 bytes)
        #   Map16 high byte buffer: $7F:C800-$7FFFFF (14336 bytes)
        # In our flat 128KB g_ram[]:
        #   $7E:C800-$7EFFFF -> g_ram[0x0C800-0x0FFFF]
        #   $7F:C800-$7FFFFF -> g_ram[0x1C800-0x1FFFF]
        # Also worth checking:
        #   $7E:1933-$1956 (level-tile buffer fragment we know matches)
        #   $7E:0EF9-$0FFF (block-related state)
        # diff_region samples every Nth byte for large regions.
        diff_region(sock, f, rec_anchor, emu_anchor, 0x0C800, 0x10000,
                    'Map16 low buffer ($7E:C800-FFFF)')
        diff_region(sock, f, rec_anchor, emu_anchor, 0x1C800, 0x20000,
                    'Map16 high buffer ($7F:C800-FFFF)')
    finally:
        try: sock.close()
        except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        _kill()


if __name__ == '__main__':
    main()
