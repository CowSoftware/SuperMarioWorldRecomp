#!/usr/bin/env python3
"""SMWDisX conformance harness v0.1 (MVP).

Check every function declared in recomp/bank*.cfg against SMWDisX's
label-level classification. For each function, run snesrecomp's decoder
and flag any instruction whose ADDRESS lands inside a SMWDisX DATA
region.

We sidestep the "parse .asm and track PC" problem by using SMWDisX/SMW_U.sym
as the source of truth for label→address mappings. Labels self-classify
by prefix:

    CODE_XXaabb, ReturnXXaabb -> code
    DATA_XXaabb, EDATA_XXaabb -> data
    everything else           -> unknown (don't use for checks)

For each emitted insn at pc P, we find the nearest label addr <= P.
If that label is DATA and the next label's addr > P, P is inside a
SMWDisX-declared data region -> FAIL. Otherwise OK.

This is a v0.1 check: catches "decoder walked into data" cleanly, without
needing to parse .asm instruction lines or track M/X state. Future versions
can add mnemonic/operand parity by parsing the bank asm text line-by-line
once the conditional-assembly drift is handled.

Known v0.1 limitations:
  * decode_func runs with validate_branches=False, which is what the
    real pipeline uses for body decode; it walks fall-through past RTS
    until end_addr. So a FAIL at pc P inside the function's body is a
    real bug, but a FAIL at a pc well past the stated end is often
    just the decoder following fall-through into the next function.
    Filter by `pc - addr` relative offset when triaging.
  * We skip `func` entries that are in `cfg.skip` — no gen body exists
    to compare against. Un-skip a function to get it through the
    harness.
  * Non-prefixed labels (TilesetMAP16Loc, BombExplosionX, etc.) are
    classified 'unknown' — they contribute nothing to FAIL detection.
    Coverage grows if later versions parse bank_XX.asm for the first
    non-label line after each such label.

Usage:
    python tools/smwdisx_compare.py                # all banks
    python tools/smwdisx_compare.py --bank 02      # one bank
    python tools/smwdisx_compare.py --func NAME    # one function
    python tools/smwdisx_compare.py --verbose      # show per-insn detail on FAIL
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
# Config loading
# ---------------------------------------------------------------------------

def load_cfgs(rom: bytes) -> Dict[str, 'recomp.Config']:
    """Load every bank cfg and populate cfg.jsl_dispatch{,_long} by
    running the recompiler's auto-detect pass. Without this, decode_func
    walks past JSL-dispatch sites into inline table bytes."""
    cfgs: Dict[str, recomp.Config] = {}
    for bank_hex in ['00', '01', '02', '03', '04', '05', '07', '0c', '0d']:
        path = RECOMP_DIR / f'bank{bank_hex}.cfg'
        if not path.exists():
            continue
        cfg = recomp.parse_config(str(path))
        recomp._auto_detect_dispatch_helpers(rom, cfg)
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


def check_function(rom: bytes, cfg, labels: List[Label], fname: str,
                   addr: int, eovr: Optional[int], mo) -> FuncResult:
    full_addr = (cfg.bank << 16) | addr
    if fname in cfg.skip:
        return FuncResult(fname, cfg.bank, addr, 'SKIP',
                          'cfg has skip directive')
    end = eovr if eovr is not None else 0x10000
    try:
        insns = recomp.decode_func(
            rom, cfg.bank, addr, end=end,
            jsl_dispatch=cfg.jsl_dispatch or None,
            jsl_dispatch_long=cfg.jsl_dispatch_long or None,
            mode_overrides=mo or None,
            exclude_ranges=cfg.exclude_ranges or None,
            known_func_starts=set(cfg.names.keys()),
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

    # For each emitted insn, find the SMWDisX region it falls in.
    for ins in insns:
        pc = ins.addr
        info = find_label_for_addr(labels, pc)
        if info is None:
            continue
        label, nxt = info
        if label.kind != 'data':
            continue
        # Is pc inside this DATA region? Region extends from label.addr
        # to nxt.addr (exclusive) if nxt exists.
        end_of_region = nxt.addr if nxt else 0x1000000
        if pc < end_of_region:
            return FuncResult(
                fname, cfg.bank, addr, 'FAIL',
                f'decoded into SMWDisX {label.name} at ${pc:06X}',
                first_divergence=(pc,
                                  f'SMWDisX={label.name} region '
                                  f'[${label.addr:06X}..${end_of_region:06X}) '
                                  f'ours={ins.mnem}'))
    return FuncResult(fname, cfg.bank, addr, 'PASS')


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(bank_filter: Optional[str], func_filter: Optional[str], verbose: bool) -> int:
    rom = load_rom(str(ROM_PATH))
    labels = load_symbols()
    cfgs = load_cfgs(rom)
    results: List[FuncResult] = []
    for bank_hex, cfg in cfgs.items():
        if bank_filter and bank_hex != bank_filter:
            continue
        for (fname, faddr, _sig, eovr, mo, _hints) in cfg.funcs:
            if func_filter and fname != func_filter:
                continue
            res = check_function(rom, cfg, labels, fname, faddr, eovr, mo)
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
