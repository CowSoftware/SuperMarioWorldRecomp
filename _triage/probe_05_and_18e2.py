"""Compare write timelines of $7E:0005 and $7E:18E2 between pre-fix
and post-fix recomp.

These two bytes gate the SpawnBounceSprite_02887D block-hit chain:
- $7E:0005 is the block-contents byte (set when Mario hits a block).
- $7E:18E2 is a flag that branches the +0x11 sprite-type adjust.

If post-fix never sets $05 to a yoshi-block-content value, that's
the regression: block-hit detection broken. If $05 is set the same
in both but $18E2 differs, the sprite-type-adjust branch differs.
If both bytes track the same in pre-fix and post-fix, the divergence
is elsewhere (likely Mario's trajectory misses the block).
"""
from __future__ import annotations
import json, pathlib, socket, subprocess, time

REPO = pathlib.Path(__file__).parent.parent
BASE = REPO / '_triage' / 'baseline'
PRE  = BASE / 'smw_pre_fix.exe'
POST = REPO / 'build' / 'bin-x64-Oracle' / 'smw.exe'  # current build = post-fix
PORT = 4377


def _kill():
    subprocess.run(['taskkill', '/F', '/IM', 'smw.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd(sock, f, line):
    sock.sendall((line + '\n').encode())
    return json.loads(f.readline())


def capture_writes(exe_path: pathlib.Path, addrs):
    _kill(); time.sleep(0.6)
    proc = subprocess.Popen([str(exe_path)], cwd=str(REPO),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    out = {}
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
        for addr in addrs:
            # Pull in chunks (limit 4096 per call).
            all_w = []
            for from_f in range(0, 800, 100):
                r = cmd(sock, f, f'wram_writes_at {addr:x} {from_f} {from_f + 100} 4096')
                all_w.extend(r.get('matches', []))
            out[addr] = all_w
        return out
    finally:
        try: sock.close()
        except Exception: pass
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        _kill()


def diff_timeline(addr_label, addr, pre_w, post_w):
    print(f'\n=== ${addr:04x} ({addr_label}) ===')
    print(f'  pre-fix:  {len(pre_w)} writes')
    print(f'  post-fix: {len(post_w)} writes')
    n = min(len(pre_w), len(post_w))
    diverge = None
    for i in range(n):
        a, b = pre_w[i], post_w[i]
        if (a.get('f') != b.get('f') or a.get('val') != b.get('val')
                or a.get('func') != b.get('func')):
            diverge = i; break
    if diverge is None and len(pre_w) != len(post_w):
        diverge = n
    if diverge is None:
        print('  TIMELINES IDENTICAL')
        # Show the unique values written and which function wrote them.
        from collections import Counter
        vals = Counter(w.get('val', '?') for w in pre_w)
        print(f'  values seen: {dict(vals.most_common(8))}')
        return
    print(f'  First divergence at index {diverge}:')
    for i in range(max(0, diverge - 2), min(max(len(pre_w), len(post_w)), diverge + 3)):
        a = pre_w[i] if i < len(pre_w) else None
        b = post_w[i] if i < len(post_w) else None
        mark = ' <-- DIVERGE' if i == diverge else ''
        a_str = (f'f={a.get("f"):>4} val={a.get("val")} func={a.get("func", "?")[:35]}'
                 if a else '<end>')
        b_str = (f'f={b.get("f"):>4} val={b.get("val")} func={b.get("func", "?")[:35]}'
                 if b else '<end>')
        print(f'    [{i:>3}] pre:  {a_str}')
        print(f'           post: {b_str}{mark}')


def main():
    addrs = [0x0005, 0x18e2]
    print('Capturing pre-fix...')
    pre = capture_writes(PRE, addrs)
    print('Capturing post-fix...')
    post = capture_writes(POST, addrs)
    diff_timeline('block-content scratch', 0x0005, pre[0x0005], post[0x0005])
    diff_timeline('spawn-flag', 0x18e2, pre[0x18e2], post[0x18e2])


if __name__ == '__main__':
    main()
