"""Triage probe: walk the always-on WRAM-write rings on both sides and
find the FIRST frame where suspect WRAM bytes diverge between recomp
and oracle. Inputs are the addresses the differ flagged as carrying
mismatched values when they were *read* — those reads are downstream
symptoms; the upstream cause is the first divergent write.

Doesn't pause / step / arm anything. Free-runs the runtime, then
queries both rings backward in history. Per the global ring rule.

Usage:
    python _triage/probe_cluster_b_root.py
"""
from __future__ import annotations
import socket, json, subprocess, time, sys, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'

# Suspect addresses derived from differ output:
#   $0083 Layer1ScrollDir   — Y at $02:A817 always rec=1 emu=2
#   $001D Layer1XPos+1      — A at $02:A823 always rec=0xff emu=0
SUSPECTS = [
    (0x0083, 'Layer1ScrollDir'),
    (0x001D, 'Layer1XPos+1'),
    (0x001C, 'Layer1XPos+0'),
    (0x001E, 'Layer1YPos+0'),
    (0x001F, 'Layer1YPos+1'),
    (0x009D, 'SpritesLocked'),  # culprit in koopa-call-chain memory
]

def kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)

def launch():
    if not EXE.exists():
        sys.exit(f'no {EXE}')
    kill()
    time.sleep(0.5)
    p = subprocess.Popen([str(EXE)], cwd=str(REPO),
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            s = socket.create_connection(('127.0.0.1', 4377), timeout=0.3)
            s.settimeout(15.0)
            return p, s
        except OSError:
            time.sleep(0.2)
    p.kill(); sys.exit('no TCP')

def cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())

def main():
    p, sock = launch()
    f = sock.makefile('r')
    print('banner:', f.readline().strip())
    try:
        # Free-run for 5 seconds — both rings record continuously.
        print('[probe] free-running 5s to populate rings...')
        time.sleep(5)
        print('[probe] frame:', cmd(sock, f, 'frame'),
              ' emu_frame:', cmd(sock, f, 'emu_frame'))

        for addr, name in SUSPECTS:
            print(f'\n=== ${addr:04x} ({name}) ===')
            rec = cmd(sock, f, f'wram_writes_at 0x{addr:x} 0 999999 256')
            emu = cmd(sock, f, f'emu_wram_writes_at 0x{addr:x} 0 999999 256')
            r_writes = rec.get('matches', []) or rec.get('writes', [])
            e_writes = emu.get('matches', [])
            print(f'  rec writes: {len(r_writes)}  emu writes: {len(e_writes)}')

            # Compare frame-aligned: each rec frame's final value vs each
            # emu frame's final value. Different counters, but each side's
            # frame sequence is monotonic — we look for FIRST disagreement
            # in (frame_index, after_value) between the two arrays.
            n = min(len(r_writes), len(e_writes))
            first_div = None
            for i in range(n):
                rv = int(r_writes[i]['val'], 0) & 0xFF if 'val' in r_writes[i] else int(r_writes[i].get('after', '0x0'), 0)
                ev = int(e_writes[i]['after'], 0)
                if rv != ev:
                    first_div = i
                    break
            if first_div is not None:
                rw = r_writes[first_div]
                ew = e_writes[first_div]
                print(f'  FIRST DIVERGE at write_idx={first_div}:')
                print(f'    rec  f={rw.get("f")}  adr={rw.get("adr")}  '
                      f'val={rw.get("val")} pc={rw.get("pc","?")} '
                      f'func={rw.get("func","?")}')
                print(f'    emu  f={ew.get("f")}  adr={ew.get("adr")}  '
                      f'after={ew.get("after")} pc={ew.get("pc","?")}')
                # Print the 3 surrounding writes for context
                lo = max(0, first_div - 1)
                hi = min(n, first_div + 3)
                print(f'  context [rec writes {lo}..{hi}]:')
                for j in range(lo, hi):
                    print(f'    {j}: f={r_writes[j].get("f")} val={r_writes[j].get("val")} pc={r_writes[j].get("pc","?")} func={r_writes[j].get("func","?")}')
                print(f'  context [emu writes {lo}..{hi}]:')
                for j in range(lo, hi):
                    print(f'    {j}: f={e_writes[j].get("f")} after={e_writes[j].get("after")} pc={e_writes[j].get("pc","?")}')
            else:
                print(f'  IDENTICAL across {n} aligned writes (or one side has no writes)')
                if r_writes:
                    print(f'  recent rec write: {r_writes[-1]}')
                if e_writes:
                    print(f'  recent emu write: {e_writes[-1]}')
    finally:
        try: sock.close()
        except Exception: pass
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()
        kill()

if __name__ == '__main__':
    main()
