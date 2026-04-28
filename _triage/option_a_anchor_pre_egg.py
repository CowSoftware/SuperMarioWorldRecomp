"""Anchor at the moment JUST BEFORE the 0x01 -> 0x2C transition.

The egg-hatch transition writes sprite_type[slot] = 0x2C. snes9x
does this; recomp's broad-fix doesn't. The bug is in the code that
DECIDES to write 0x2C — that code reads WRAM to determine whether
to fire. Comparing recomp vs snes9x WRAM at the LAST frame BEFORE
the snes9x transition tells us which input byte differs.

Strategy:
1. Find snes9x's frame F where sprite_type[8] first becomes 0x2C
   (i.e. the egg-hatch trigger fired).
2. The PREVIOUS frame F-1 is the "decision frame" — the WRAM state
   that the trigger logic read.
3. Find recomp's logical-equivalent frame: the frame where recomp's
   sprite_type[0] is still 0x01 and the same number of inner-loop
   advances have occurred (use FrameCounter or NMICounter as match).
4. Diff WRAM at those frames. The diff identifies the byte the
   trigger logic reads differently.
"""
from __future__ import annotations
import json, pathlib, socket, subprocess, time

REPO = pathlib.Path(__file__).parent.parent
EXE = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'
PORT = 4377


def _kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())


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
        time.sleep(12.0)
        # Find on snes9x: writes that put 0x2c into ANY of $9E-$AB.
        emu_2c_writes = []
        for slot in range(12):
            addr = 0x9e + slot
            r = cmd(sock, f, f'emu_wram_writes_at {addr:x} 0 99999 256')
            for m in r.get('matches', []):
                a = m.get('after', '0x00')
                try:
                    av = int(a, 0) if isinstance(a, str) else a
                except (ValueError, TypeError):
                    continue
                if av == 0x2c:
                    emu_2c_writes.append((slot, m['f'], m.get('pc', '?')))
        emu_2c_writes.sort(key=lambda t: t[1])
        print(f'snes9x 0x2C writes to sprite_type slots: {len(emu_2c_writes)}')
        for slot, fr, pc in emu_2c_writes[:8]:
            print(f'  slot {slot} @ frame {fr} pc={pc}')
        # Same for recomp.
        rec_2c_writes = []
        for slot in range(12):
            addr = 0x9e + slot
            r = cmd(sock, f, f'wram_writes_at {addr:x} 0 99999 256')
            for m in r.get('matches', []):
                a = m.get('val')
                if a is None:
                    continue
                try:
                    av = int(a, 0) if isinstance(a, str) else a
                except (ValueError, TypeError):
                    continue
                if av == 0x2c:
                    rec_2c_writes.append((slot, m.get('f'), m.get('func', '?')))
        rec_2c_writes.sort(key=lambda t: t[1] or 0)
        print(f'\nrecomp 0x2C writes to sprite_type slots: {len(rec_2c_writes)}')
        for slot, fr, fn in rec_2c_writes[:8]:
            print(f'  slot {slot} @ frame {fr} func={fn}')
        if not emu_2c_writes:
            print('\nsnes9x ring did not capture any 0x2C write — try shorter run')
            return
        if not rec_2c_writes:
            print('\nrecomp produces NO 0x2C transition — this is the bug.')
            print('Searching upstream for what gates the 0x2C write...')
        # Anchor: the snes9x frame just BEFORE the first 0x2C write.
        emu_egg_frame = emu_2c_writes[0][1]
        emu_anchor = max(1, emu_egg_frame - 1)
        print(f'\nsnes9x decision frame (one before 0x2C write): {emu_anchor}')
        # Find recomp's logical-equivalent frame. Use sprite_type[0]==0x01
        # AND any active sprite-related WRAM. We want recomp's "matching"
        # frame — same logical demo step. Heuristic: pick recomp frame
        # where slot-0-type is still 0x01 (pre-transition).
        h = cmd(sock, f, 'history').get('history', {})
        rec_oldest, rec_newest = h.get('oldest', -1), h.get('newest', -1)
        print(f'recomp history: {rec_oldest}..{rec_newest}')
        # At which recomp frame did sprite_type[0] FIRST become 0x01?
        rec_first_01 = None
        for slot in range(12):
            addr = 0x9e + slot
            r = cmd(sock, f, f'wram_writes_at {addr:x} 0 99999 64')
            for m in r.get('matches', []):
                a = m.get('val')
                if a is None: continue
                try:
                    av = int(a, 0) if isinstance(a, str) else a
                except (ValueError, TypeError):
                    continue
                if av == 0x01:
                    rec_first_01 = (slot, m.get('f'))
                    break
            if rec_first_01:
                break
        print(f'recomp first 0x01 spawn: slot {rec_first_01}')
        # snes9x first 0x01 spawn:
        emu_first_01 = None
        for slot in range(12):
            addr = 0x9e + slot
            r = cmd(sock, f, f'emu_wram_writes_at {addr:x} 0 99999 64')
            for m in r.get('matches', []):
                a = m.get('after', '0x00')
                try:
                    av = int(a, 0) if isinstance(a, str) else a
                except (ValueError, TypeError):
                    continue
                if av == 0x01:
                    emu_first_01 = (slot, m.get('f'))
                    break
            if emu_first_01:
                break
        print(f'snes9x first 0x01 spawn: slot {emu_first_01}')
        # The "logical equivalent" is N frames after spawn where N matches
        # snes9x's "egg-precursor → 0x2C" delay. snes9x: spawn at frame X,
        # 0x2C transition at X + K. Recomp's 0x2C should fire at recomp
        # spawn-frame + K. If recomp's frame doesn't reach spawn+K with
        # 0x2C, the trigger failed.
        if emu_first_01 and rec_first_01:
            emu_K = emu_egg_frame - emu_first_01[1]
            print(f'snes9x: 0x2C fires {emu_K} frames after 0x01 spawn')
            rec_target_frame = rec_first_01[1] + emu_K
            if rec_target_frame > rec_newest:
                rec_target_frame = rec_newest
            print(f'recomp target frame (spawn + {emu_K}): {rec_target_frame}')
            # Diff WRAM at rec_target_frame vs emu_egg_frame.
            rec_w = cmd(sock, f, f'dump_frame_wram {rec_target_frame} 0 8192').get('hex', '').replace(' ', '')
            # Sample sprite-state regions: $9E-$BF, $14C8-$14EF (statuses
            # + extra bytes), $1540-$155F (sprite timer), $151C-$1527.
            regions = [
                ('sprite types',       0x009E, 0x00B0),
                ('sprite Y',           0x00D8, 0x00E4),
                ('sprite X',           0x00E4, 0x00F0),
                ('sprite status',      0x14C8, 0x14D4),
                ('sprite "blocked"',   0x1588, 0x1594),
                ('sprite timer 1540',  0x1540, 0x154C),
                ('sprite egg state',   0x151C, 0x1528),
            ]
            print(f'\nWRAM diff at decision frames (rec={rec_target_frame}, emu={emu_egg_frame - 1}):')
            for name, lo, hi in regions:
                diffs = []
                for off in range(lo, hi):
                    rec_pos = off * 2
                    if rec_pos + 2 > len(rec_w):
                        # off in $1xxx is past 8192-byte dump; query single byte
                        r = cmd(sock, f, f'dump_frame_wram {rec_target_frame} {off:x} 1')
                        rec_b = r.get('hex', '').replace(' ', '')
                        rec = int(rec_b, 16) if rec_b else 0
                    else:
                        rec = int(rec_w[rec_pos:rec_pos+2], 16)
                    r = cmd(sock, f, f'emu_wram_at_frame {emu_anchor} {off:x}')
                    emu_v = r.get('val', '0x00')
                    try:
                        emu = int(emu_v, 0) if isinstance(emu_v, str) else emu_v
                    except (ValueError, TypeError):
                        emu = 0
                    if rec != emu:
                        diffs.append((off, rec, emu))
                print(f'  {name} (${lo:04x}-${hi-1:04x}): {len(diffs)}/{hi-lo} diffs')
                for off, r, e in diffs[:8]:
                    print(f'    $7E:{off:04x}: rec=0x{r:02x} emu=0x{e:02x}')
    finally:
        try: sock.close()
        except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        _kill()


if __name__ == '__main__':
    main()
