"""Validate that recomp and snes9x produce IDENTICAL WRAM after boot
under same (idle) inputs. If true, deterministic-sync harness is
trivial (let both sides boot independently, then compare per-frame).
If false, document where they diverge.

Strategy:
  1. Free-run both sides for N seconds (long enough to reach
     GameMode=$07 + a few frames of attract demo).
  2. Pull recomp WRAM via dump_ram, snes9x WRAM via emu_read_wram.
  3. Diff byte-by-byte; report distinct addresses.
  4. Also pull each side's frame counter so we know what wall-clock
     point each was at.

Doesn't pause/step/inject. Free-runs only. Per the global
ring-buffer / never-time-attach rule.
"""
from __future__ import annotations
import socket, json, subprocess, time, sys, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'

def kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)

def launch():
    if not EXE.exists(): sys.exit(f'no {EXE}')
    kill(); time.sleep(0.5)
    p = subprocess.Popen([str(EXE)], cwd=str(REPO),
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            s = socket.create_connection(('127.0.0.1', 4377), timeout=0.3)
            s.settimeout(60.0)
            return p, s
        except OSError: time.sleep(0.2)
    p.kill(); sys.exit('no TCP')

def cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())

def chunked_dump_recomp(sock, f, addr_lo, addr_hi):
    """dump_ram returns hex compactly; chunk to keep JSON manageable."""
    out = bytearray()
    chunk = 4096
    a = addr_lo
    while a < addr_hi:
        n = min(chunk, addr_hi - a)
        r = cmd(sock, f, f'dump_ram 0x{a:x} {n}')
        h = r.get('hex', '')
        out.extend(bytes.fromhex(h))
        a += n
    return bytes(out)

def chunked_dump_emu(sock, f, addr_lo, addr_hi):
    out = bytearray()
    chunk = 4096
    a = addr_lo
    while a < addr_hi:
        n = min(chunk, addr_hi - a)
        r = cmd(sock, f, f'emu_read_wram 0x{a:x} {n}')
        h = r.get('hex', '').replace(' ', '')
        out.extend(bytes.fromhex(h))
        a += n
    return bytes(out)

def main():
    p, sock = launch()
    f = sock.makefile('r')
    print('banner:', f.readline().strip())
    try:
        # Different free-run windows to see how divergence grows.
        for wait_s in (0.5, 1, 2, 4, 8):
            time.sleep(wait_s if wait_s == 0.5 else (wait_s - (
                0.5 + sum([1, 2, 4, 8][:max(0, [0.5,1,2,4,8].index(wait_s)-1)])))
            )
            rec_frame = cmd(sock, f, 'frame')
            emu_frame = cmd(sock, f, 'emu_frame')
            print(f'\n=== t~{wait_s}s — rec_frame={rec_frame.get("frame")} '
                  f'emu_frame={emu_frame.get("frame")} ===')

            # Pull WRAM low-8KB only; that's where SMW gameplay state lives.
            # Pulling all 128KB would be slower and dominated by uninit zones.
            rec = chunked_dump_recomp(sock, f, 0, 0x2000)
            emu = chunked_dump_emu(sock, f, 0, 0x2000)
            assert len(rec) == len(emu) == 0x2000, (len(rec), len(emu))
            diffs = [(i, rec[i], emu[i]) for i in range(len(rec)) if rec[i] != emu[i]]
            print(f'  diffs (low 8KB): {len(diffs)} / 8192 bytes')
            if diffs and len(diffs) <= 30:
                for a, rv, ev in diffs:
                    print(f'    ${a:04x}: rec={rv:02x} emu={ev:02x}')
            elif diffs:
                # Histogram by 256-byte page
                pages = {}
                for a, _, _ in diffs:
                    pages[a >> 8] = pages.get(a >> 8, 0) + 1
                top = sorted(pages.items(), key=lambda kv: -kv[1])[:10]
                print(f'  top diff pages: {[(f"${p:02x}xx", c) for p,c in top]}')
                print(f'  first 5 diffs: '
                      f'{[(f"${a:04x}", f"{r:02x}/{e:02x}") for a,r,e in diffs[:5]]}')
                print(f'  last 5 diffs:  '
                      f'{[(f"${a:04x}", f"{r:02x}/{e:02x}") for a,r,e in diffs[-5:]]}')
    finally:
        try: sock.close()
        except: pass
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()
        kill()

if __name__ == '__main__':
    main()
