"""Audit leaf functions for exit-(M, X) variant mismatches.

For every cfg `func` entry F whose body has no JSR/JSL under ANY
(m, x) entry combo (true leaf), decode F under all four entry
states and compute exit (m, x). Classify F as:

  - NO MUTATION        — every entry's exit == that entry; no
                         directive needed.
  - CONVERGENT MUTATION — at least one entry mutates AND all four
                         entries produce the same exit (m, x). A
                         single `exit_mx_at` directive covers all
                         entries; this is the SUBGROUP A class
                         the existing leaf auto-router misses
                         when the cfg-declared entry happens to
                         be non-mutating.
  - DIVERGENT MUTATION  — at least one entry mutates and the four
                         exits don't all agree. The cfg directive's
                         per-PC granularity can't express
                         per-variant exit, so the singular fix
                         per discovered variant is the audit
                         fallback (SUBGROUP B).

Functions already covered by an `exit_mx_at` directive in any
cfg are skipped.

Output: a markdown report on stdout (or to --out) listing each
non-trivial finding with its per-entry exit table and a suggested
cfg directive if convergent.

Usage:
    python tools/audit_leaf_exit_mx_variants.py \\
        --rom smw.sfc --cfg-dir recomp \\
        [--out tools/audit_leaf_exit_mx_variants_report.md]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Dict, List, Optional, Tuple

_THIS_DIR = pathlib.Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
_SNESRECOMP_DIR = _PROJECT_ROOT / 'snesrecomp'
_RECOMPILER_DIR = _SNESRECOMP_DIR / 'recompiler'
for p in (str(_RECOMPILER_DIR), str(_SNESRECOMP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from v2.cfg_loader import load_bank_cfg  # noqa: E402
from v2.decoder import decode_function, analyze_function_exit_mx  # noqa: E402
from v2.exit_mx_autoroute import detect_and_route as autoroute_exit_mx  # noqa: E402

_BANK_CFG_RE = re.compile(r'bank([0-9A-Fa-f]{2})\.cfg$')

_MX_COMBOS: List[Tuple[int, int]] = [(0, 0), (0, 1), (1, 0), (1, 1)]


def _decode_safe(rom, bank, addr16, em, ex, end):
    try:
        graph = decode_function(rom, bank, addr16,
                                entry_m=em, entry_x=ex, end=end)
    except Exception:
        return None
    if not graph.insns:
        return None
    return graph


def _graph_has_call(graph) -> bool:
    for di in graph.insns.values():
        if di.insn.mnem in ('JSR', 'JSL'):
            return True
    return False


class FunctionReport:
    """Per-function audit result."""

    def __init__(self, bank: int, addr16: int, name: str,
                 cfg_em: int, cfg_ex: int):
        self.bank = bank
        self.addr16 = addr16
        self.name = name
        self.cfg_em = cfg_em
        self.cfg_ex = cfg_ex
        # (em, ex) -> (exit_m, exit_x) or None if undecodable / non-leaf
        self.exits: Dict[Tuple[int, int],
                         Optional[Tuple[int, int]]] = {}
        self.non_leaf = False
        self.undecodable = False

    @property
    def addr_24(self) -> int:
        return (self.bank << 16) | (self.addr16 & 0xFFFF)

    def classify(self) -> str:
        """Return one of:
          'no_mutation'      — every entry's exit == that entry
          'router_catches'   — cfg-declared entry's exit != entry
                                (current auto-router commits a
                                directive for this; no action)
          'convergent_miss'  — ALL FOUR entries decode AND agree on
                                a single exit AND ≥1 entry mutates
                                AND cfg-declared entry doesn't
                                mutate (auto-router class-fix
                                candidate that escaped pass 1)
          'divergent'        — all four entries decode but exits
                                don't all agree (needs per-variant
                                directive)
          'partial_decode'   — at least one (m,x) entry fails to
                                decode; informational only — the
                                auto-router conservatively requires
                                all four to decode before committing
          'non_leaf'         — body contains JSR/JSL
          'undecodable'      — couldn't decode any variant

        The classification matches the auto-router's commit rule
        exactly: convergent_miss is reported only when the
        auto-router COULD have committed a directive but didn't
        (because pass 1 saw cfg entry stable). Sites with partial
        decodes are bucketed separately so the audit numbers track
        the auto-router's behavior.
        """
        if self.non_leaf:
            return 'non_leaf'
        decoded_exits = [e for e in self.exits.values() if e is not None]
        if not decoded_exits:
            return 'undecodable'
        if any(e is None for e in self.exits.values()):
            return 'partial_decode'
        cfg_exit = self.exits.get((self.cfg_em, self.cfg_ex))
        assert cfg_exit is not None
        cfg_ex_m, cfg_ex_x = cfg_exit
        if cfg_ex_m != self.cfg_em or cfg_ex_x != self.cfg_ex:
            return 'router_catches'
        mutations = [
            (em, ex, ex_m, ex_x)
            for (em, ex), e in self.exits.items()
            for ex_m, ex_x in [e]
            if em != ex_m or ex != ex_x
        ]
        if not mutations:
            return 'no_mutation'
        unique_exits = set(decoded_exits)
        if len(unique_exits) == 1:
            return 'convergent_miss'
        return 'divergent'

    def convergent_exit(self) -> Optional[Tuple[int, int]]:
        """If convergent, return the single (exit_m, exit_x)."""
        decoded_exits = [e for e in self.exits.values() if e is not None]
        if not decoded_exits:
            return None
        unique = set(decoded_exits)
        if len(unique) == 1:
            return next(iter(unique))
        return None


def audit(rom: bytes, parsed) -> List[FunctionReport]:
    """Run the audit over all parsed cfgs."""
    # Collect declared exit_mx_at sites — skip these (already handled).
    declared = set()
    for bank, _path, cfg in parsed:
        for (b_id, addr16, _em, _ex) in cfg.exit_mx_at:
            declared.add((b_id & 0xFF, addr16 & 0xFFFF))

    reports: List[FunctionReport] = []
    for bank, _path, cfg in parsed:
        for entry in cfg.entries:
            if not entry.name:
                continue
            addr16 = entry.start & 0xFFFF
            if (bank, addr16) in declared:
                continue
            r = FunctionReport(bank, addr16, entry.name,
                               entry.entry_m & 1, entry.entry_x & 1)
            for em, ex in _MX_COMBOS:
                graph = _decode_safe(rom, bank, addr16, em, ex,
                                     entry.end)
                if graph is None:
                    r.exits[(em, ex)] = None
                    continue
                if _graph_has_call(graph):
                    r.non_leaf = True
                    r.exits[(em, ex)] = None
                    continue
                ex_m, ex_x = analyze_function_exit_mx(graph)
                if ex_m is None or ex_x is None:
                    r.exits[(em, ex)] = None
                    continue
                r.exits[(em, ex)] = (ex_m & 1, ex_x & 1)
            reports.append(r)
    return reports


def _format_exit_table(r: FunctionReport) -> str:
    """Render the per-entry exit table as a markdown table."""
    rows = ['| entry (m,x) | exit (m,x) | mutates? |',
            '|---|---|---|']
    for em, ex in _MX_COMBOS:
        e = r.exits.get((em, ex))
        if e is None:
            rows.append(f'| ({em},{ex}) | — | (undecodable) |')
        else:
            ex_m, ex_x = e
            mut = ' **yes**' if (em != ex_m or ex != ex_x) else 'no'
            rows.append(f'| ({em},{ex}) | ({ex_m},{ex_x}) |{mut} |')
    return '\n'.join(rows)


def format_report(reports: List[FunctionReport]) -> str:
    """Render the full audit report."""
    classes: Dict[str, List[FunctionReport]] = {
        'router_catches': [], 'convergent_miss': [], 'divergent': [],
        'partial_decode': [], 'no_mutation': [], 'non_leaf': [],
        'undecodable': [],
    }
    for r in reports:
        classes[r.classify()].append(r)

    lines = []
    lines.append('# Leaf exit-(M, X) variant audit\n')
    lines.append('Generated by `tools/audit_leaf_exit_mx_variants.py`.\n')
    lines.append('## Summary\n')
    lines.append(f'- Total cfg `func` entries audited: **{len(reports)}**')
    lines.append(f'- Router catches (cfg-declared entry mutates — '
                 f'current auto-router already commits): '
                 f'**{len(classes["router_catches"])}**')
    lines.append(f'- Convergent miss (subgroup A — '
                 f'auto-router class-fix candidates): '
                 f'**{len(classes["convergent_miss"])}**')
    lines.append(f'- Divergent (subgroup B — needs per-variant '
                 f'directive): **{len(classes["divergent"])}**')
    lines.append(f'- Partial decode (some (m,x) entries failed to '
                 f'decode; auto-router conservatively skips): '
                 f'**{len(classes["partial_decode"])}**')
    lines.append(f'- No mutation: **{len(classes["no_mutation"])}**')
    lines.append(f'- Non-leaf (contains JSR/JSL — skipped): '
                 f'**{len(classes["non_leaf"])}**')
    lines.append(f'- Undecodable: **{len(classes["undecodable"])}**\n')

    lines.append('## Subgroup A — convergent miss '
                 '(auto-router class fix candidates)\n')
    if not classes['convergent_miss']:
        lines.append('_None._\n')
    else:
        lines.append('cfg-declared entry doesn\'t mutate, but ≥1 other '
                     '(m, x) entry mutates AND all four entries produce '
                     'the same exit. The current leaf auto-router '
                     '(snesrecomp `14c8eea`) scans only the cfg-declared '
                     'entry and misses these. Extending it to scan all '
                     '4 (m, x) combos (still commit only when all '
                     'exits agree) closes the class.\n')
        lines.append('| addr | name | cfg entry (m,x) | exit (m,x) | '
                     'suggested cfg |')
        lines.append('|---|---|---|---|---|')
        for r in sorted(classes['convergent_miss'],
                        key=lambda x: x.addr_24):
            e = r.convergent_exit()
            assert e is not None
            ex_m, ex_x = e
            lines.append(
                f'| ${r.bank:02X}:{r.addr16:04X} | `{r.name}` | '
                f'({r.cfg_em},{r.cfg_ex}) | ({ex_m},{ex_x}) | '
                f'`exit_mx_at {r.bank:02X}{r.addr16:04x} {ex_m} {ex_x}` |'
            )
        lines.append('')

    lines.append('## Subgroup B — divergent '
                 '(needs per-variant or "preserve" cfg directive)\n')
    if not classes['divergent']:
        lines.append('_None._\n')
    else:
        lines.append('Different entries produce different exits. A '
                     'single `exit_mx_at` cannot cover all entries. '
                     'Hand-annotate based on which variants are '
                     'actually discovered at emit time (each row '
                     'below shows the per-entry exit so you can pick '
                     'the value matching live callers).\n')
        for r in sorted(classes['divergent'], key=lambda x: x.addr_24):
            lines.append(
                f'### ${r.bank:02X}:{r.addr16:04X} `{r.name}` '
                f'(cfg entry ({r.cfg_em},{r.cfg_ex}))\n'
            )
            lines.append(_format_exit_table(r))
            lines.append('')

    return '\n'.join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--rom', required=True)
    p.add_argument('--cfg-dir', required=True)
    p.add_argument('--out', default=None,
                   help='Optional path to write the report (else stdout)')
    args = p.parse_args()

    with open(args.rom, 'rb') as f:
        rom = f.read()
    cfg_dir = pathlib.Path(args.cfg_dir)
    cfgs = sorted(cfg_dir.glob('bank*.cfg'))
    if not cfgs:
        print(f'no bank*.cfg under {cfg_dir}', file=sys.stderr)
        return 2

    parsed: List[Tuple[int, pathlib.Path, object]] = []
    for cfg_path in cfgs:
        m = _BANK_CFG_RE.search(cfg_path.name)
        if not m:
            continue
        bank = int(m.group(1), 16)
        try:
            cfg = load_bank_cfg(str(cfg_path))
        except Exception as e:
            print(f'  PARSE-FAIL bank ${bank:02X}: '
                  f'{type(e).__name__}: {e}', file=sys.stderr)
            continue
        parsed.append((bank, cfg_path, cfg))

    # Run the auto-router in-memory so its synthesized directives count
    # as "declared" for the audit. Without this step the audit reports
    # sites the auto-router would catch at regen time as still
    # outstanding, which is misleading.
    autorouted = autoroute_exit_mx(parsed, rom)
    print(f'auto-router synthesised {len(autorouted)} directive(s)',
          file=sys.stderr)

    reports = audit(rom, parsed)
    out = format_report(reports)
    if args.out:
        pathlib.Path(args.out).write_text(out, encoding='utf-8')
        print(f'wrote {args.out}')
    else:
        sys.stdout.write(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
