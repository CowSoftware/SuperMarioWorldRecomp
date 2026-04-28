"""List functions whose codegen changed under the phi-prealloc fix.

For each gen file, walks both pre-fix (HEAD~1) and post-fix (HEAD)
versions, segments by function, and reports functions whose body
differs. Output is sorted by diff size (largest first) — those are
the most-disturbed functions and best initial candidates for the
'hand-code via skip + handbody' workaround.
"""
import re
import subprocess
from collections import defaultdict


def get_file(rev: str, path: str) -> str:
    r = subprocess.run(['git', 'show', f'{rev}:{path}'],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''


def split_funcs(src: str):
    """Return [(name, addr_hex, lines)] for each function definition."""
    funcs = []
    cur_name = None; cur_addr = None; cur_lines = []
    in_func = False
    for line in src.splitlines():
        m = re.match(r'^[A-Za-z][A-Za-z0-9_*]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{\s*//\s*([0-9a-f]+)', line)
        if m:
            if in_func:
                funcs.append((cur_name, cur_addr, '\n'.join(cur_lines)))
            cur_name = m.group(1)
            cur_addr = m.group(2)
            cur_lines = [line]
            in_func = True
            continue
        if in_func:
            cur_lines.append(line)
            if line == '}':
                funcs.append((cur_name, cur_addr, '\n'.join(cur_lines)))
                in_func = False
    return funcs


def diff_bank(bank_name: str, path: str):
    pre = get_file('0b7846b', path)
    post = get_file('HEAD', path)
    if not pre or not post:
        print(f'{bank_name}: file missing in one revision')
        return []
    pre_funcs = {(n, a): body for n, a, body in split_funcs(pre)}
    post_funcs = {(n, a): body for n, a, body in split_funcs(post)}
    changed = []
    for key in sorted(post_funcs.keys() | pre_funcs.keys()):
        pre_body = pre_funcs.get(key, '')
        post_body = post_funcs.get(key, '')
        if pre_body != post_body:
            n, a = key
            delta = abs(len(post_body.splitlines()) - len(pre_body.splitlines()))
            changed.append((n, a, len(pre_body.splitlines()),
                            len(post_body.splitlines()), delta))
    return changed


BANKS = [
    ('bank_00', 'src/gen/smw_00_gen.c'),
    ('bank_01', 'src/gen/smw_01_gen.c'),
    ('bank_02', 'src/gen/smw_02_gen.c'),
    ('bank_05', 'src/gen/smw_05_gen.c'),
]


def main():
    for bank_name, path in BANKS:
        changed = diff_bank(bank_name, path)
        # Sort by delta (line-count change) descending — biggest reshuffles first.
        changed.sort(key=lambda t: -t[4])
        print(f'\n=== {bank_name}: {len(changed)} changed funcs ===')
        for n, a, pre_n, post_n, delta in changed[:25]:
            print(f'  ${a}  {n:55s}  pre={pre_n:>5}  post={post_n:>5}  delta={delta:+d}')


if __name__ == '__main__':
    main()
