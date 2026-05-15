"""Audit cfg `name` directives for usage.

A cfg `name <hex_addr_24> <symbol_name> [sig:...]` registers a friendly
symbol name for the address — used by the v2 codegen's _NAME_RESOLVER
when emitting cross-bank Call sites. Without an entry, codegen falls
back to a `bank_BB_AAAA` synthetic name.

For each `name` entry we classify by:

  - UNUSED: the symbol does not appear in any generated C file. Either
    the address is never the target of a Call (in which case the name
    entry is pure clutter) or the resolution always emits a synthetic
    name (unlikely once name is in the resolver).

  - DUPLICATE_OF_FUNC: the same address is also covered by a `func`
    entry in the SAME or another cfg. The `func` entry names the
    function; the `name` line is redundant noise.

  - ALIAS_ONLY: name is genuinely external — the address is in
    another bank and there's no `func` for it (typical Codex
    wrapper-fix cross-bank alias) — OR the name is referenced in
    generated C but no `func` declares it (HLE replacements like
    SmwRunDecompressFromWRAM, or `func` is hand-coded in src/).

Audit output writes per-category tables to
tools/audit_name_directive_usage_report.md. Hand-review the UNUSED
candidates before removing — some may be intentional forward
declarations awaiting future use.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Set

_THIS_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

# Match a `name <addr_hex> <symbol> [sig:...] [comment]` line.
_NAME_RE = re.compile(
    r"^name\s+([0-9a-fA-F]+)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
_FUNC_RE = re.compile(
    r"^func\s+([A-Za-z_][A-Za-z0-9_]*)\s+([0-9a-fA-F]+)"
)
_BANK_RE = re.compile(r"bank([0-9a-fA-F]+)\.cfg$")


@dataclass
class NameEntry:
    bank: int
    addr_24: int
    symbol: str
    cfg_path: str

    @property
    def addr_str(self) -> str:
        return f"${self.addr_24:06X}"


@dataclass
class FuncEntry:
    bank: int
    addr_24: int
    name: str


def parse_cfgs(cfg_dir: pathlib.Path):
    names: List[NameEntry] = []
    func_addrs: Dict[int, FuncEntry] = {}
    for cfg_path in sorted(cfg_dir.glob("bank*.cfg")):
        m = _BANK_RE.search(cfg_path.name)
        if not m:
            continue
        bank = int(m.group(1), 16)
        for raw in cfg_path.read_bytes().splitlines():
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            ms = _NAME_RE.match(line)
            if ms:
                addr_hex = ms.group(1)
                symbol = ms.group(2)
                addr_24 = int(addr_hex, 16) & 0xFFFFFF
                # 4-hex addresses are bank-local (cfg sometimes writes
                # `name 9d3c FOO` with no bank prefix); resolve via cfg
                # bank.
                if len(addr_hex) <= 4:
                    addr_24 = (bank << 16) | (addr_24 & 0xFFFF)
                names.append(NameEntry(bank=bank, addr_24=addr_24,
                                       symbol=symbol, cfg_path=cfg_path.name))
                continue
            mf = _FUNC_RE.match(line)
            if mf:
                func_name = mf.group(1)
                addr_hex = mf.group(2)
                addr_24 = int(addr_hex, 16) & 0xFFFFFF
                if len(addr_hex) <= 4:
                    addr_24 = (bank << 16) | (addr_24 & 0xFFFF)
                func_addrs[addr_24] = FuncEntry(bank=bank,
                                                addr_24=addr_24,
                                                name=func_name)
    return names, func_addrs


def scan_emitted_usage(gen_dir: pathlib.Path, symbols: Set[str]) -> Dict[str, int]:
    """Return {symbol -> count_of_occurrences} across .c/.h files.

    Match the symbol with an OPTIONAL `_M{0,1}X{0,1}` variant suffix —
    codegen emits per-variant function bodies named `<symbol>_M1X1`
    etc., so a bare `\\bsymbol\\b` match misses every callsite. We
    scan src/gen (regen output) AND src/ (hand-written gen_stubs.c
    and other HLE backings).
    """
    counts = {s: 0 for s in symbols}
    if not symbols:
        return counts
    pat = re.compile(
        r"\b(" + "|".join(re.escape(s) for s in symbols)
        + r")(?:_M[01]X[01])?\b"
    )
    paths = list(gen_dir.glob("*.c")) + list(gen_dir.glob("*.h"))
    # Also scan src/ for hand-written backings (src/gen_stubs.c etc.).
    src_dir = pathlib.Path("src")
    if src_dir.exists():
        paths += [p for p in src_dir.glob("*.c") if p.is_file()]
        paths += [p for p in src_dir.glob("*.h") if p.is_file()]
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in pat.finditer(text):
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def _format_report(unused: List[NameEntry],
                   duplicate_of_func: List[tuple],
                   alias_only: List[NameEntry]) -> str:
    lines = ["# `name` directive usage audit",
             "",
             "Generated by `tools/audit_name_directive_usage.py`.",
             ""]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total `name` entries: **{len(unused) + len(duplicate_of_func) + len(alias_only)}**")
    lines.append(f"- UNUSED (no reference in emitted C): **{len(unused)}**")
    lines.append(f"- DUPLICATE_OF_FUNC (same address has cfg `func`): **{len(duplicate_of_func)}**")
    lines.append(f"- ALIAS_ONLY (real cross-bank/HLE alias): **{len(alias_only)}**")
    lines.append("")
    if unused:
        lines.append("## UNUSED")
        lines.append("")
        lines.append("`name` entries whose symbol does not appear in any generated "
                     "C output. Candidates for removal — but verify each is not "
                     "a forward declaration awaiting upcoming work.")
        lines.append("")
        lines.append("| Bank | Addr | Symbol | cfg |")
        lines.append("|---|---|---|---|")
        for e in sorted(unused, key=lambda x: (x.bank, x.addr_24, x.symbol)):
            lines.append(f"| ${e.bank:02X} | {e.addr_str} | `{e.symbol}` | {e.cfg_path} |")
        lines.append("")
    if duplicate_of_func:
        lines.append("## DUPLICATE_OF_FUNC")
        lines.append("")
        lines.append("Address already declared as `func` (with its own canonical "
                     "name). The `name` entry adds an alias. Often legitimate when "
                     "the alias name is referenced separately, but worth confirming.")
        lines.append("")
        lines.append("| Bank | Addr | `name` symbol | `func` name | cfg |")
        lines.append("|---|---|---|---|---|")
        for e, fn in sorted(duplicate_of_func, key=lambda t: (t[0].bank, t[0].addr_24)):
            same = "**same**" if e.symbol == fn.name else fn.name
            lines.append(f"| ${e.bank:02X} | {e.addr_str} | `{e.symbol}` | "
                         f"`{same}` | {e.cfg_path} |")
        lines.append("")
    if alias_only:
        lines.append("## ALIAS_ONLY")
        lines.append("")
        lines.append(f"{len(alias_only)} entries — cross-bank wrapper aliases (Codex "
                     "pattern per CLAUDE.md), HLE function markers, or true "
                     "external references. Likely all load-bearing. Listed for "
                     "completeness; not a cleanup target by default.")
        lines.append("")
    return "\n".join(lines) + "\n"


_NAME_LINE_BYTES = re.compile(
    rb"^name\s+([0-9a-fA-F]+)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _apply_duplicate_removals(cfg_dir: pathlib.Path,
                              duplicates) -> int:
    """Delete cfg `name <addr> <symbol>` lines where (addr,symbol) is
    also covered by a `func` declaration with the SAME symbol.
    Reads + writes as bytes so CRLF/LF endings survive unchanged.
    Returns total lines deleted."""
    # Index target (bank, addr_24, symbol) tuples.
    targets: Dict[int, Set[tuple]] = {}
    for entry, _func in duplicates:
        targets.setdefault(entry.bank, set()).add(
            (entry.addr_24 & 0xFFFFFF, entry.symbol)
        )
    total = 0
    for cfg_path in sorted(cfg_dir.glob("bank*.cfg")):
        m = _BANK_RE.search(cfg_path.name)
        if not m:
            continue
        bank = int(m.group(1), 16)
        bank_targets = targets.get(bank, set())
        if not bank_targets:
            continue
        raw = cfg_path.read_bytes()
        out_chunks = []
        deleted = 0
        for line in raw.splitlines(True):
            ms = _NAME_LINE_BYTES.match(line)
            if ms:
                addr_hex = ms.group(1).decode("ascii")
                symbol = ms.group(2).decode("ascii")
                addr_24 = int(addr_hex, 16) & 0xFFFFFF
                if len(addr_hex) <= 4:
                    addr_24 = (bank << 16) | (addr_24 & 0xFFFF)
                if (addr_24, symbol) in bank_targets:
                    deleted += 1
                    continue  # drop the line
            out_chunks.append(line)
        if deleted:
            cfg_path.write_bytes(b"".join(out_chunks))
            print(f"  {cfg_path.name}: deleted {deleted} duplicate name lines")
            total += deleted
    return total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cfg-dir", default="recomp")
    p.add_argument("--gen-dir", default="src/gen")
    p.add_argument("--out", default="tools/audit_name_directive_usage_report.md")
    p.add_argument("--apply", action="store_true",
                   help="Delete DUPLICATE_OF_FUNC name lines from cfg files")
    args = p.parse_args()

    cfg_dir = pathlib.Path(args.cfg_dir)
    gen_dir = pathlib.Path(args.gen_dir)

    names, func_addrs = parse_cfgs(cfg_dir)
    print(f"Parsed {len(names)} name entries from cfgs")
    print(f"Parsed {len(func_addrs)} func addresses")

    # Build symbol set, scan generated C for usage.
    symbols = sorted({n.symbol for n in names})
    counts = scan_emitted_usage(gen_dir, set(symbols))

    unused: List[NameEntry] = []
    duplicate_of_func: List[tuple] = []
    alias_only: List[NameEntry] = []
    for n in names:
        ref_count = counts.get(n.symbol, 0)
        func_at_addr = func_addrs.get(n.addr_24)
        if ref_count == 0:
            unused.append(n)
        elif func_at_addr is not None:
            duplicate_of_func.append((n, func_at_addr))
        else:
            alias_only.append(n)

    report = _format_report(unused, duplicate_of_func, alias_only)
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print(f"  UNUSED:            {len(unused)}")
    print(f"  DUPLICATE_OF_FUNC: {len(duplicate_of_func)}")
    print(f"  ALIAS_ONLY:        {len(alias_only)}")
    if args.apply:
        print()
        print("--apply: deleting DUPLICATE_OF_FUNC name lines from cfg files...")
        n = _apply_duplicate_removals(cfg_dir, duplicate_of_func)
        print(f"Total name lines deleted: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
