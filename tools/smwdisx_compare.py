#!/usr/bin/env python3
"""SMWDisX conformance harness v0.2.

Two checks run per cfg function:

  v0.1 (code-vs-data): flag instructions whose address lands inside a
  SMWDisX DATA region. Uses SMW_U.sym labels to classify addresses.
  Catches "decoder walked into data" cleanly.

  v0.2 (mnemonic parity): parse bank_XX.asm line-by-line into a
  per-address mnemonic map. For each emitted insn at addr P, compare
  the mnemonic against what SMWDisX says. A mismatch means the decoder
  read different bytes than SMWDisX did at the same address.

PC tracking is anchor-reset at every `LABEL:` line where LABEL matches
`(CODE|DATA|EDATA|Return|ADDR)_XXaabb` — the anchor immediately corrects
any drift from mis-sized instructions. Coverage grows as more label-
anchored blocks are reached.

US-ROM branch is selected for all `if ver_is_...(!_VER)` conditional
blocks. Macros `%BorW`, `%WorB`, `%WorL_X`, `%LorW_X`, `%LorW` expand
per U-ROM rules (see SMWDisX/macros.asm).

Known v0.2 limitations:
  * Operand parity is NOT checked yet — SMWDisX operands are symbolic
    labels while ours are literal hex. v0.3 will resolve via SMW_U.sym.
  * M/X state is NOT tracked. For immediate-mode mnems without suffix
    (rare in SMWDisX — most carry .B/.W), we fall back to literal hex
    width.
  * `%insert_empty(...)` macro is skipped (it emits version-dependent
    fill bytes that we treat as data).
  * `con($J,$U,$SS,$E0,$E1)` picker resolves to index 1 (U).

Usage:
    python tools/smwdisx_compare.py                # all banks
    python tools/smwdisx_compare.py --bank 02      # one bank
    python tools/smwdisx_compare.py --func NAME    # one function
    python tools/smwdisx_compare.py --verbose      # per-FAIL detail
"""
from __future__ import annotations

import argparse
import bisect
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
SMWDISX = REPO / 'SMWDisX'
RECOMP_DIR = REPO / 'recomp'
ROM_PATH = REPO / 'smw.sfc'
SYM_PATH = SMWDISX / 'SMW_U.sym'

sys.path.insert(0, str(REPO / 'snesrecomp' / 'recompiler'))
import recomp                                         # noqa: E402
from snes65816 import load_rom                        # noqa: E402


# ---------------------------------------------------------------------------
# Symbol table
# ---------------------------------------------------------------------------

@dataclass
class Label:
    addr: int
    name: str
    kind: str  # 'code', 'data', 'unknown'


def classify_label(name: str) -> str:
    if name.startswith(('CODE_', 'Return')):
        return 'code'
    if name.startswith(('DATA_', 'EDATA_')):
        return 'data'
    return 'unknown'


def load_symbols() -> List[Label]:
    """Parse SMW_U.sym — one `ADDRESS NAME` per line, sorted by address."""
    labels: List[Label] = []
    with SYM_PATH.open(encoding='utf-8', errors='replace') as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith(';') or line.startswith(':'):
                continue
            # Line format: AABBCCDD NAME
            m = re.match(r'^([0-9A-Fa-f]{6,8})\s+([:\S].*)$', line)
            if not m:
                continue
            addr = int(m.group(1), 16)
            name = m.group(2).strip()
            if name.startswith(':'):
                continue  # macro start markers
            labels.append(Label(addr, name, classify_label(name)))
    labels.sort(key=lambda l: l.addr)
    return labels


def find_label_for_addr(labels: List[Label], pc: int) -> Optional[Tuple[Label, Optional[Label]]]:
    """Return (label_at_or_before_pc, next_label_or_None).

    Useful for asking "is pc inside this label's region?" — the region
    extends from label.addr up to next_label.addr (exclusive).
    """
    keys = [l.addr for l in labels]
    i = bisect.bisect_right(keys, pc) - 1
    if i < 0:
        return None
    nxt = labels[i + 1] if i + 1 < len(labels) else None
    return labels[i], nxt


# ---------------------------------------------------------------------------
# SMWDisX asm parser for v0.2 mnemonic parity
# ---------------------------------------------------------------------------

# Instructions that are always 1 byte (no operand).
_ONE_BYTE_MNEMS = {
    'INX', 'DEX', 'INY', 'DEY',
    'TAX', 'TAY', 'TXA', 'TYA', 'TSX', 'TXS', 'TYX', 'TXY',
    'TCS', 'TSC', 'TCD', 'TDC', 'TCE',
    'PHA', 'PLA', 'PHX', 'PLX', 'PHY', 'PLY', 'PHB', 'PLB', 'PHK',
    'PHP', 'PLP', 'PHD', 'PLD',
    'CLC', 'SEC', 'CLD', 'SED', 'CLV', 'CLI', 'SEI', 'XCE', 'NOP',
    'RTS', 'RTL', 'RTI', 'STP', 'WAI', 'XBA',
}

# 2-byte PC-relative branches.
_BRANCH_2 = {'BEQ', 'BNE', 'BCS', 'BCC', 'BMI', 'BPL', 'BVS', 'BVC', 'BRA'}

# 2-byte immediate-only ops.
_IMM_2 = {'REP', 'SEP', 'COP', 'BRK', 'WDM'}

# 3-byte relative (BRL) or PER.
_REL16_3 = {'BRL', 'PER'}

# 4-byte long jumps/calls.
_LONG_4 = {'JSL', 'JML'}

# Label name prefixes that encode an address in hex (6 hex digits).
_LABEL_ADDR_RE = re.compile(r'^(?:CODE|DATA|EDATA|Return|ADDR)_([0-9A-Fa-f]{6})$')

# Macro expansion map for U ROM (!_VER=!__VER_U).
# Each entry maps `macro_name -> (suffix, addressing_form)`.
# addressing_form: '' = just <addr>, ',X' = <addr>,X
_U_MACROS = {
    'BorW':    ('.W', ''),    # addr  (.B if J, .W otherwise → .W for U)
    'WorB':    ('.B', ''),    # addr  (.W if J, .B otherwise → .B for U)
    'WorL_X':  ('.L', ',X'),  # addr,X (.W if J, .L otherwise → .L for U)
    'LorW_X':  ('.W', ',X'),  # addr,X (.L if J, .W otherwise → .W for U)
    'LorW':    ('.W', ''),    # addr  (.L if J, .W otherwise → .W for U)
}


def _insn_size(mnem: str, suffix: str, operand: str) -> Optional[int]:
    """Compute encoded instruction size in bytes, or None if we can't tell."""
    m = mnem.upper()
    # Accumulator form.
    if m in ('ASL', 'LSR', 'ROL', 'ROR', 'INC', 'DEC'):
        if suffix == '' and operand.strip().upper() == 'A':
            return 1
    if m in _ONE_BYTE_MNEMS and not operand.strip():
        return 1
    if m in _BRANCH_2:
        return 2
    if m in _REL16_3:
        return 3
    if m in _IMM_2:
        return 2
    if m in _LONG_4:
        return 4
    if m == 'JMP':
        # JMP abs, JMP (abs), JMP (abs,X) — all 3. JMP [abs] (= JML) = 4.
        if operand.strip().startswith('['):
            return 4
        return 3
    if m == 'JSR':
        return 3  # JSR abs or JSR (abs,X)
    if m == 'PEA':
        return 3
    if m == 'PEI':
        return 2
    if m in ('MVN', 'MVP'):
        return 3
    # Explicit width suffix wins for normal load/store/etc.
    if suffix == '.B':
        return 2
    if suffix == '.W':
        return 3
    if suffix == '.L':
        return 4
    # No suffix — fall back to operand inspection.
    op = operand.strip()
    if op.startswith('#$'):
        hex_digits = op[2:]
        # Trim trailing comma/close-paren artifacts (shouldn't happen for imm).
        hex_digits = re.sub(r'[^0-9A-Fa-f]', '', hex_digits)
        if len(hex_digits) <= 2:
            return 2
        return 3
    # Bare mnemonic (no operand visible) → probably 1-byte.
    if not op:
        return 1
    # Safe fallback: assume ABS (3) — the anchor reset on the next
    # CODE_XX label will correct if we got it wrong.
    return 3


_COMMENT_RE = re.compile(r';.*$')
_ORG_RE = re.compile(r'^\s*ORG\s+\$([0-9A-Fa-f]+)', re.IGNORECASE)
_LABEL_LINE_RE = re.compile(r'^([A-Za-z_][\w]*)\s*:')
_INSTR_RE = re.compile(
    r'^\s*'
    r'(?P<mnem>[A-Za-z]{2,4})'
    r'(?P<suffix>\.[BWL])?'
    r'(?:\s+(?P<operand>[^;]*?))?'
    r'\s*$'
)
_MACRO_RE = re.compile(
    r'^\s*%(?P<name>\w+)\((?P<args>[^)]*)\)\s*$'
)
_DATA_RE = re.compile(r'^\s*(d[bwdl])\s+(.+)$', re.IGNORECASE)


def _eval_ver_predicate(expr: str) -> Optional[bool]:
    """Evaluate a `ver_is_XXX(!_VER)` predicate for the U ROM."""
    m = re.match(r'ver_is_(\w+)\s*\(\s*!_VER\s*\)', expr.strip())
    if not m:
        return None
    # U-ROM truth table (see SMWDisX/macros.asm head).
    u = {
        'japanese': False, 'english': True,
        'hires': False, 'lores': True,
        'pal': False, 'ntsc': True,
        'arcade': False, 'console': True,
        'english_console': True,
        'has_rev_gfx': False,  # J or E1
    }
    return u.get(m.group(1))


def _expand_macro(macro_name: str, args: str) -> Optional[Tuple[str, str, str]]:
    """Expand a macro call to (mnem, suffix, operand_text) for U ROM.

    Returns None for macros we don't expand (data-emitting ones, etc.)."""
    macro_name = macro_name.strip()
    if macro_name not in _U_MACROS:
        return None
    suffix, addr_form = _U_MACROS[macro_name]
    parts = [p.strip() for p in args.split(',', 1)]
    if len(parts) != 2:
        return None
    cmd, addr = parts
    return (cmd.upper(), suffix, f'{addr}{addr_form}')


def parse_bank(bank_hex: str) -> Tuple[Dict[int, Tuple[str, str]], Set[int]]:
    """Parse SMWDisX/bank_XX.asm into (mnem_map, data_addrs).

    mnem_map: {full_addr: (mnem, suffix)} — one entry per instruction.
    data_addrs: set of addresses we saw as data bytes (db/dw/dl/dd).
    Using the parser's per-byte data set (vs label-based region lookup)
    avoids false positives from anonymous labels (`+`/`-`) that aren't
    in SMW_U.sym — label-based would mis-flag an anonymous-labeled code
    block wedged between a DATA_XX label and the next CODE_XX label as
    data.
    """
    bank = int(bank_hex, 16)
    path = SMWDISX / f'bank_{bank_hex.upper()}.asm'
    if not path.exists():
        return {}, set()

    out: Dict[int, Tuple[str, str]] = {}
    data_addrs: Set[int] = set()
    pc: Optional[int] = None
    # Nested conditional stack: each entry is (is_active, has_else_fired).
    cond_stack: List[Tuple[bool, bool]] = []

    def is_active() -> bool:
        return all(a for a, _ in cond_stack)

    with path.open(encoding='utf-8', errors='replace') as fp:
        for raw in fp:
            line = raw.rstrip('\n')
            stripped = _COMMENT_RE.sub('', line).rstrip()
            if not stripped.strip():
                continue
            body = stripped.strip()
            low = body.lower()

            # Conditional directives.
            if low.startswith('if '):
                verdict = _eval_ver_predicate(body[3:])
                cond_stack.append((verdict if verdict is not None else False, False))
                continue
            if low == 'else':
                if cond_stack:
                    active, had_else = cond_stack.pop()
                    cond_stack.append((not active, True))
                continue
            if low == 'endif':
                if cond_stack:
                    cond_stack.pop()
                continue
            if not is_active():
                continue

            # ORG directive.
            m = _ORG_RE.match(stripped)
            if m:
                pc = int(m.group(1), 16)
                continue

            # Label line (anchor-reset PC if name encodes address).
            m = _LABEL_LINE_RE.match(body)
            if m:
                lbl = m.group(1)
                am = _LABEL_ADDR_RE.match(lbl)
                if am:
                    pc = int(am.group(1), 16)
                # Labels that don't encode address just stay — they mark
                # positions that later code/data entries can reference,
                # but don't tell us where we are.
                continue
            # Anonymous labels: just "+", "-", "++", "--".
            if re.match(r'^[+\-]+$', body):
                continue

            # Macro invocation.
            m = _MACRO_RE.match(body)
            if m:
                expanded = _expand_macro(m.group('name'), m.group('args'))
                if expanded and pc is not None:
                    mnem, suffix, operand = expanded
                    size = _insn_size(mnem, suffix, operand)
                    if size is not None:
                        if (pc >> 16) == bank:
                            out[pc] = (mnem, suffix)
                        pc += size
                # Macros we don't expand (e.g. %insert_empty) advance PC
                # by an unknown amount — we can't track through them, so
                # leave pc None so we wait for the next anchor. But
                # %insert_empty explicitly emits data, so marking pc=None
                # is the correct conservative choice.
                else:
                    pc = None
                continue

            # Data directives.
            m = _DATA_RE.match(body)
            if m:
                directive = m.group(1).lower()
                items_raw = m.group(2)
                items = [x for x in items_raw.split(',') if x.strip()]
                size_per = {'db': 1, 'dw': 2, 'dl': 3, 'dd': 4}[directive]
                if pc is not None and (pc >> 16) == bank:
                    for off in range(size_per * len(items)):
                        data_addrs.add(pc + off)
                if pc is not None:
                    pc += size_per * len(items)
                continue

            # Assembler directives we can't track through — invalidate pc
            # until the next anchor.
            if body.split(None, 1)[0].lower() in (
                    'incsrc', 'incbin', 'table', 'pushtable', 'pulltable',
                    'warnpc', 'check', 'autoclean', 'freespace',
                    'namespace', 'pushbase', 'pullbase', 'base',
                    'fillbyte', 'fill', 'pad', 'optimize',
                    'assert', 'print', 'expression', 'math',
                    'define', 'undef', 'while', 'macro', 'endmacro',
                    'function'):
                pc = None
                continue

            # Instruction line.
            m = _INSTR_RE.match(body)
            if m:
                mnem = m.group('mnem').upper()
                suffix = m.group('suffix') or ''
                operand = m.group('operand') or ''
                size = _insn_size(mnem, suffix, operand)
                if size is None:
                    pc = None
                    continue
                if pc is not None and (pc >> 16) == bank:
                    out[pc] = (mnem, suffix)
                if pc is not None:
                    pc += size
                continue

            # Something we don't understand — invalidate pc until the
            # next label anchor.
            pc = None

    return out, data_addrs


def parse_bank_mnems(bank_hex: str) -> Dict[int, Tuple[str, str]]:
    """Legacy wrapper returning only the mnem_map (pre-data_addrs split)."""
    mnems, _ = parse_bank(bank_hex)
    return mnems


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_cfgs(rom: bytes) -> Dict[str, 'recomp.Config']:
    """Load every bank cfg and run the same preprocessing the real
    regen pipeline does:

      1. Auto-detect dispatch helpers (jsl_dispatch / jsl_dispatch_long)
         so decode_func knows where inline tables live.
      2. Run discover_bank to find every JSR/JSL/dispatch-table target.
         Auto-promote each discovered intra-bank address to a synthetic
         `auto_BB_AAAA` func so downstream decode_func / known_func_starts
         sees them as known code. This mirrors run_config's auto-promote
         pass (recomp.py ~5201). Without it, the harness's decoder
         sees fewer known functions than the real regen does and
         reports phantom data-byte FAILs where the real regen doesn't
         (dispatch handler addresses show up as unknown, so the dispatch
         cap break triggers past the real table end).
      3. Promote sub-entries declared in cfg.names whose address falls
         inside an existing func range.
    """
    from discover import discover_bank as _discover_bank  # noqa: E402
    cfgs: Dict[str, recomp.Config] = {}
    for bank_hex in ['00', '01', '02', '03', '04', '05', '07', '0c', '0d']:
        path = RECOMP_DIR / f'bank{bank_hex}.cfg'
        if not path.exists():
            continue
        cfg = recomp.parse_config(str(path))
        recomp._auto_detect_dispatch_helpers(rom, cfg)
        # Iterate discover_bank to fixpoint (same as run_config does).
        _seed_set = {a for _, a, *_ in cfg.funcs}
        _existing_addrs = set(_seed_set)
        _existing_local_names = {
            a & 0xFFFF for a in cfg.names if (a >> 16) == cfg.bank
        }
        _discovered_local: set = set()
        for _round in range(8):
            try:
                _round_local, _round_cross = _discover_bank(
                    rom, cfg.bank,
                    external_seeds=_seed_set,
                    jsl_dispatch=set(cfg.jsl_dispatch or []),
                    jsl_dispatch_long=set(cfg.jsl_dispatch_long or []),
                )
            except Exception:
                break
            _prev = len(_discovered_local)
            _discovered_local |= _round_local
            if len(_discovered_local) == _prev:
                break
            _seed_set |= _discovered_local
        for _addr in sorted(_discovered_local):
            if _addr < 0x8000 or _addr > 0xFFFF:
                continue
            if _addr in _existing_addrs or _addr in _existing_local_names:
                continue
            if _addr in cfg.no_autodiscover:
                continue
            in_exclude = any(er_s <= _addr <= er_e
                             for er_s, er_e in cfg.exclude_ranges)
            if in_exclude:
                continue
            _auto_name = f'auto_{cfg.bank:02X}_{_addr:04X}'
            cfg.funcs.append((_auto_name, _addr, 'void()', None, {}, {}))
            cfg.names[(cfg.bank << 16) | _addr] = _auto_name
            cfg.sigs[(cfg.bank << 16) | _addr] = 'void()'
            _existing_addrs.add(_addr)
        cfg.funcs.sort(key=lambda t: t[1])
        recomp.promote_sub_entries(rom, cfg)
        cfgs[bank_hex] = cfg
    return cfgs


# ---------------------------------------------------------------------------
# Per-function check
# ---------------------------------------------------------------------------

@dataclass
class FuncResult:
    name: str
    bank: int
    addr: int
    status: str  # 'PASS' | 'FAIL' | 'SKIP' | 'UNKNOWN'
    reason: str = ''
    first_divergence: Optional[Tuple[int, str]] = None  # (pc, detail)


def check_function(rom: bytes, cfg, labels: List[Label],
                   mnem_map: Dict[int, Tuple[str, str]],
                   data_addrs: Set[int],
                   fname: str,
                   addr: int, eovr: Optional[int], mo) -> FuncResult:
    full_addr = (cfg.bank << 16) | addr
    if fname in cfg.skip:
        return FuncResult(fname, cfg.bank, addr, 'SKIP',
                          'cfg has skip directive')
    end = eovr if eovr is not None else 0x10000
    known_func_addrs = set(cfg.names.keys())
    for _fn, _addr, *_r in cfg.funcs:
        known_func_addrs.add((cfg.bank << 16) | _addr)
    try:
        insns = recomp.decode_func(
            rom, cfg.bank, addr, end=end,
            jsl_dispatch=cfg.jsl_dispatch or None,
            jsl_dispatch_long=cfg.jsl_dispatch_long or None,
            dispatch_known_addrs=known_func_addrs,
            mode_overrides=mo or None,
            exclude_ranges=cfg.exclude_ranges or None,
            known_func_starts=known_func_addrs,
            validate_branches=False,
        )
    except Exception as e:
        return FuncResult(fname, cfg.bank, addr, 'UNKNOWN',
                          f'decode_func raised: {type(e).__name__}: {e}')
    if not insns:
        return FuncResult(fname, cfg.bank, addr, 'UNKNOWN', 'no insns')

    # Does SMWDisX have a code label at the function's entry? If not,
    # the function isn't an entry point SMWDisX recognizes — still report
    # because we can check against DATA regions, but tag it as unusual.
    entry_info = find_label_for_addr(labels, full_addr)
    entry_label: Optional[Label] = None
    if entry_info:
        entry_label, _ = entry_info
        if entry_label.addr != full_addr:
            entry_label = None

    # For each emitted insn, run two checks in order:
    #   (A) code-vs-data: if addr is in the parser's data_addrs set
    #       (bytes the parser saw advance PC via db/dw/dl/dd), FAIL.
    #   (B) mnemonic parity: if mnem_map has an entry at addr and
    #       it disagrees with our mnemonic, FAIL.
    for ins in insns:
        pc = ins.addr
        if pc in data_addrs:
            return FuncResult(
                fname, cfg.bank, addr, 'FAIL',
                f'decoded into SMWDisX data byte at ${pc:06X}',
                first_divergence=(
                    pc, f'SMWDisX=data, ours={ins.mnem}'))

        # v0.2: mnemonic parity. Only check when SMWDisX has an anchor.
        smwdisx_ent = mnem_map.get(pc)
        if smwdisx_ent is not None:
            smwdisx_mnem, _suffix = smwdisx_ent
            if _mnems_agree(smwdisx_mnem, ins.mnem):
                continue
            return FuncResult(
                fname, cfg.bank, addr, 'FAIL',
                f'mnem mismatch at ${pc:06X}: SMWDisX={smwdisx_mnem}, '
                f'ours={ins.mnem}',
                first_divergence=(
                    pc,
                    f'SMWDisX={smwdisx_mnem}, ours={ins.mnem}'))
    return FuncResult(fname, cfg.bank, addr, 'PASS')


def _mnems_agree(smwdisx: str, ours: str) -> bool:
    """Mnemonic equivalence for harness purposes.

    SMWDisX uses canonical Apple/WLA-DX naming; our decoder matches
    exactly for all standard 65816 mnemonics. The only cases that need
    normalization:

      * BRK vs STP (both 1-byte in their respective modes — not an alias)
      * JMP.L / JML: SMWDisX writes JML for long-addr JMP ($5C). Our
        decoder uses JMP with LONG mode. Treat them as equivalent at
        the mnem level (operand check later).
    """
    if smwdisx == ours:
        return True
    if {smwdisx, ours} == {'JML', 'JMP'}:
        return True
    return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(bank_filter: Optional[str], func_filter: Optional[str], verbose: bool) -> int:
    rom = load_rom(str(ROM_PATH))
    labels = load_symbols()
    cfgs = load_cfgs(rom)
    # Parse every targeted bank once, cache (mnem_map, data_addrs).
    bank_parses: Dict[str, Tuple[Dict[int, Tuple[str, str]], Set[int]]] = {}
    for bank_hex in cfgs:
        if bank_filter and bank_hex != bank_filter:
            continue
        bank_parses[bank_hex] = parse_bank(bank_hex)
    results: List[FuncResult] = []
    for bank_hex, cfg in cfgs.items():
        if bank_filter and bank_hex != bank_filter:
            continue
        mnem_map, data_addrs = bank_parses.get(bank_hex, ({}, set()))
        for (fname, faddr, _sig, eovr, mo, _hints) in cfg.funcs:
            if func_filter and fname != func_filter:
                continue
            res = check_function(rom, cfg, labels, mnem_map, data_addrs,
                                 fname, faddr, eovr, mo)
            results.append(res)

    # Per-bank rollup.
    by_bank: Dict[int, Dict[str, int]] = {}
    for r in results:
        d = by_bank.setdefault(
            r.bank, {'PASS': 0, 'FAIL': 0, 'SKIP': 0, 'UNKNOWN': 0})
        d[r.status] += 1

    print()
    print(f'{"bank":<6} {"pass":>6} {"fail":>6} {"skip":>6} {"unknown":>8} {"total":>7}')
    print('-' * 46)
    tot = {'PASS': 0, 'FAIL': 0, 'SKIP': 0, 'UNKNOWN': 0}
    for bank, d in sorted(by_bank.items()):
        n = sum(d.values())
        for k in tot:
            tot[k] += d[k]
        print(f'${bank:02X}    {d["PASS"]:>6} {d["FAIL"]:>6} {d["SKIP"]:>6} '
              f'{d["UNKNOWN"]:>8} {n:>7}')
    n = sum(tot.values())
    print('-' * 46)
    print(f'{"total":<6} {tot["PASS"]:>6} {tot["FAIL"]:>6} {tot["SKIP"]:>6} '
          f'{tot["UNKNOWN"]:>8} {n:>7}')
    if n - tot['SKIP'] - tot['UNKNOWN'] > 0:
        checkable = tot['PASS'] + tot['FAIL']
        print(f'pass rate (of checkable): '
              f'{100 * tot["PASS"] / checkable:.1f}%'
              f' ({tot["PASS"]}/{checkable})')

    fails = [r for r in results if r.status == 'FAIL']
    if fails:
        print()
        print(f'{len(fails)} FAIL:')
        for r in fails[:50 if not verbose else 500]:
            print(f'  [{r.bank:02X}] {r.name} @ ${r.addr:04X} — {r.reason}')
            if r.first_divergence and verbose:
                pc, detail = r.first_divergence
                print(f'     at ${pc:06X}: {detail}')
        if len(fails) > 50 and not verbose:
            print(f'  ... and {len(fails) - 50} more (use --verbose)')

    if verbose and func_filter:
        # Show per-insn trace for a single function.
        r = results[0] if results else None
        if r and r.status != 'SKIP':
            print()
            print(f'--- {r.name} decoded insns ---')
            # Re-decode for print.
            bank_hex = f'{r.bank:02x}'
            cfg = cfgs[bank_hex]
            end = 0x10000
            for fname, faddr, _, eovr, mo, _hints in cfg.funcs:
                if fname == r.name:
                    end = eovr if eovr else 0x10000
                    break
            insns = recomp.decode_func(
                rom, r.bank, r.addr, end=end,
                jsl_dispatch=cfg.jsl_dispatch or None,
                jsl_dispatch_long=cfg.jsl_dispatch_long or None,
                mode_overrides=mo or None,
                exclude_ranges=cfg.exclude_ranges or None,
                known_func_starts=set(cfg.names.keys()),
                validate_branches=False,
            )
            for ins in insns[:40]:
                info = find_label_for_addr(labels, ins.addr)
                lbl = info[0].name if info else '?'
                kind = info[0].kind if info else '?'
                print(f'  ${ins.addr:06X} [{kind:7}] {ins.mnem:<6} '
                      f'({lbl}+${ins.addr - info[0].addr:X})')

    return 1 if tot['FAIL'] else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bank', help='Limit to one bank (hex, e.g. 02)')
    ap.add_argument('--func', help='Limit to one function name')
    ap.add_argument('--verbose', '-v', action='store_true')
    args = ap.parse_args()
    rc = run(args.bank, args.func, args.verbose)
    sys.exit(rc)


if __name__ == '__main__':
    main()
