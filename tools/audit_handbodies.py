#!/usr/bin/env python3
"""Hand-body audit for src/*.c. Classifies each hand-body into:

  DEAD                  — zero callers anywhere in parent or snesrecomp/.
  SUPERSEDING_CODEGEN   — name also appears in recomp_func_registry (gen
                          has a function with the same name — link conflict
                          unless one shadows the other; rip the hand body
                          and let the gen version take over).
  REGISTRY_BY_ADDR      — cfg has `name 0xAABBCC Hand` and the same addr
                          is a `func` in some bank.cfg — i.e. gen emits a
                          body at the same ROM address but under a
                          different name. Route callers to the gen name
                          and rip the hand body.
  IRREDUCIBLE           — has callers, no gen overlap. Likely WRAM helper,
                          TCP integration, platform glue. Stays.

Prints a structured report. Does NOT modify any files.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / 'src'
GEN = REPO / 'src' / 'gen'
RECOMP = REPO / 'recomp'
SUBREPO = REPO / 'snesrecomp'
REGISTRY_C = GEN / 'recomp_func_registry.c'

HAND_RE = re.compile(
    r'^(?:static\s+)?(?P<ret>\w[\w\s\*]*?)\s+(?P<name>\w+)\s*\([^)]*\)\s*\{',
    re.MULTILINE,
)
SKIP_RETS = {'if', 'for', 'while', 'switch', 'do', 'return', 'else'}


def collect_hand_bodies():
    """Return [(file, name)] for every hand body in src/*.c (excluding gen/)."""
    out = []
    for p in sorted(SRC.glob('*.c')):
        text = p.read_text(encoding='utf-8', errors='replace')
        for m in HAND_RE.finditer(text):
            if m.group('ret').strip() in SKIP_RETS:
                continue
            out.append((p.name, m.group('name')))
    return out


def collect_registry_names():
    """Names declared in recomp_func_registry.c (excluding registry table itself)."""
    if not REGISTRY_C.exists():
        return set()
    text = REGISTRY_C.read_text(encoding='utf-8', errors='replace')
    # Forward decls: `void Name(...);` or `RetX Name(...);`
    decl_re = re.compile(r'^(?:[\w\s\*]+?)\s+(\w+)\s*\([^;]*\)\s*;', re.MULTILINE)
    return {m.group(1) for m in decl_re.finditer(text)}


def collect_cfg_name_addr_map():
    """Return {name: full_addr} from `name 0xAABBCC Foo` lines in bank cfgs."""
    name_re = re.compile(r'^\s*name\s+0x([0-9a-fA-F]+)\s+(\w+)', re.MULTILINE)
    out = {}
    for p in sorted(RECOMP.glob('bank*.cfg')):
        if 'bisect' in p.name:
            continue
        text = p.read_text(encoding='utf-8', errors='replace')
        for m in name_re.finditer(text):
            addr = int(m.group(1), 16)
            out[m.group(2)] = addr
    return out


def collect_cfg_func_addrs():
    """Return {full_addr: cfg_func_name} from `func name 0xAABBCC ...` lines."""
    func_re = re.compile(
        r'^\s*func\s+(\w+)\s+0x([0-9a-fA-F]+)', re.MULTILINE)
    out = {}
    for p in sorted(RECOMP.glob('bank*.cfg')):
        if 'bisect' in p.name:
            continue
        text = p.read_text(encoding='utf-8', errors='replace')
        for m in func_re.finditer(text):
            addr = int(m.group(2), 16)
            out[addr] = m.group(1)
    return out


def count_callers(name, body_file):
    """Count references to `name` across both repos.

    A "reference" is any \\bname\\b occurrence that is NOT:
      * the body's own opening line (`<ret> name(args) {`)
      * a pure forward declaration (`<ret> name(args);` with no body)

    We count bare-name matches (not `name(`) so function-pointer
    registrations like `SDL_AddTimer(t, my_cb, NULL)` and registry
    table entries (`{ "Foo", Foo, ... }`) are caught.

    Returns (call_site_count, [unique_files_with_calls]).
    """
    pat = re.compile(rf'\b{re.escape(name)}\b')
    body_open_re = re.compile(
        rf'^(?:static\s+)?\w[\w\s\*]*?\s+{re.escape(name)}\s*\([^)]*\)\s*\{{')
    # decl_re: must start with a real type-prefix token, not a statement
    # keyword like `return`. Restrict to known type prefixes plus
    # static/extern. Anything else that ends `name(...)` followed by `;`
    # is a call-as-statement, not a decl.
    type_prefix = (
        r'(?:static\s+|extern\s+|const\s+|inline\s+)*'
        r'(?:void|bool|char|int|short|long|signed|unsigned|float|double|'
        r'uint\d+|int\d+|size_t|ssize_t|intptr_t|uintptr_t|ptrdiff_t|'
        r'Ret[A-Z]\w*|Point[A-Z]\w*|[A-Z]\w*_?t)'
    )
    decl_re = re.compile(
        rf'^{type_prefix}[\w\s\*]*?\s+{re.escape(name)}\s*\([^;]*\)\s*;')
    sites = set()
    total = 0
    roots = [REPO / 'src', REPO / 'recomp', REPO / 'assets', SUBREPO]
    for root in roots:
        if not root.exists():
            continue
        for ext in ('*.c', '*.h', '*.cpp'):
            for p in root.rglob(ext):
                # Skip pure auto-generated decl headers — funcs.h, gen forward
                # decls, registry forward decls. These are not "callers".
                if p.name == 'funcs.h':
                    continue
                if p.parent.name == 'gen' and p.name.endswith('_gen.c'):
                    # gen bodies could be callers (cross-bank JSL) but their
                    # forward-decl preamble is noise. Count cautiously.
                    pass
                try:
                    text = p.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                for line in text.splitlines():
                    if not pat.search(line):
                        continue
                    # Strip body-open and pure decl lines
                    if body_open_re.match(line.lstrip()):
                        continue
                    if decl_re.match(line.lstrip()):
                        continue
                    total += 1
                    sites.add(str(p.relative_to(REPO)))
    return total, sorted(sites)


def main():
    bodies = collect_hand_bodies()
    registry_names = collect_registry_names()
    cfg_name_addrs = collect_cfg_name_addr_map()
    cfg_func_addrs = collect_cfg_func_addrs()

    classes = {'DEAD': [], 'SUPERSEDING_CODEGEN': [], 'REGISTRY_BY_ADDR': [],
               'IRREDUCIBLE': []}

    for fname, name in bodies:
        callers, sites = count_callers(name, fname)

        in_registry = name in registry_names
        addr = cfg_name_addrs.get(name)
        gen_at_addr = cfg_func_addrs.get(addr) if addr is not None else None

        if callers == 0:
            classes['DEAD'].append((fname, name, sites))
        elif in_registry:
            classes['SUPERSEDING_CODEGEN'].append((fname, name, callers, sites))
        elif gen_at_addr and gen_at_addr != name:
            classes['REGISTRY_BY_ADDR'].append(
                (fname, name, addr, gen_at_addr, callers, sites))
        else:
            classes['IRREDUCIBLE'].append((fname, name, callers, sites))

    # Report
    print(f'\n=== Hand-body audit: {len(bodies)} bodies in src/*.c ===\n')

    print(f'\nDEAD ({len(classes["DEAD"])}): zero callers, safe to rip')
    print('-' * 60)
    for fname, name, _sites in sorted(classes['DEAD']):
        print(f'  {fname:30s} {name}')

    print(f'\nSUPERSEDING_CODEGEN ({len(classes["SUPERSEDING_CODEGEN"])}): '
          'name in registry — gen version exists')
    print('-' * 60)
    for fname, name, callers, _sites in sorted(classes['SUPERSEDING_CODEGEN']):
        print(f'  {fname:30s} {name:40s} ({callers} callers)')

    print(f'\nREGISTRY_BY_ADDR ({len(classes["REGISTRY_BY_ADDR"])}): '
          'gen at same ROM addr under different name')
    print('-' * 60)
    for fname, name, addr, gen_name, callers, _sites in sorted(classes['REGISTRY_BY_ADDR']):
        print(f'  {fname:30s} {name:30s} 0x{addr:06x} -> {gen_name} '
              f'({callers} callers)')

    print(f'\nIRREDUCIBLE ({len(classes["IRREDUCIBLE"])}): keep')
    print('-' * 60)
    for fname, name, callers, sites in sorted(classes['IRREDUCIBLE']):
        site_summary = ','.join(sorted(set(sites))[:3])
        print(f'  {fname:30s} {name:35s} ({callers}) sites: {site_summary}')

    # Summary line for grep-friendly tracking
    print(f'\nSUMMARY  total={len(bodies)} '
          f'dead={len(classes["DEAD"])} '
          f'superseding={len(classes["SUPERSEDING_CODEGEN"])} '
          f'by_addr={len(classes["REGISTRY_BY_ADDR"])} '
          f'irreducible={len(classes["IRREDUCIBLE"])}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
