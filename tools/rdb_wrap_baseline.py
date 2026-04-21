"""Transform a committed-baseline src/gen/*.c so every WRAM store becomes
an RDB_STORE8 / RDB_STORE16 call, without reintroducing recomp.py drift.

Why: regenerating banks with --reverse-debug also applies unrelated
recompiler changes that haven't propagated to the committed baseline.
Those unrelated changes may introduce regressions. For Tier-1 litmus
work we only want the RDB wrapping, not the drift.

Use sparingly. The canonical path is to regen normally and accept drift.
"""
import re
import sys

def wrap(src: str) -> str:
    # *(uint16*)(g_ram + <addr_expr>) = <val>;  -> RDB_STORE16(<addr_expr>, <val>);
    src = re.sub(
        r'\*\(uint16\*\)\(g_ram \+ ([^)]+?)\) = ([^;]+);',
        r'RDB_STORE16(\1, \2);',
        src,
    )
    # g_ram[<addr_expr>] = <val>;  -> RDB_STORE8(<addr_expr>, <val>);
    # Careful: address expression can contain [] nesting? For the committed
    # generator output, g_ram[...] addressing never nests. Use non-greedy.
    src = re.sub(
        r'g_ram\[([^\]]+?)\] = ([^;]+);',
        r'RDB_STORE8(\1, \2);',
        src,
    )
    return src


def main():
    if len(sys.argv) != 3:
        print('usage: rdb_wrap_baseline.py <input.c> <output.c>', file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], 'rb') as f:
        src = f.read().decode('utf-8', errors='replace')
    out = wrap(src)
    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        f.write(out)
    n8 = out.count('RDB_STORE8(')
    n16 = out.count('RDB_STORE16(')
    print(f'wrote {sys.argv[2]}: {n8} byte stores, {n16} word stores wrapped')


if __name__ == '__main__':
    main()
