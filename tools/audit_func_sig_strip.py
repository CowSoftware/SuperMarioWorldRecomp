"""Audit + strip v1-era `sig:...` tokens and `# AUTO` / `# MANUAL`
provenance markers from cfg `func` / `name` lines.

snesrecomp v2 IGNORES `sig:` entirely — see
snesrecomp/recompiler/v2/cfg_loader.py:7. Every v2 function is
`void f(CpuState *cpu)`. The `# AUTO` / `# MANUAL` markers tagged
whether the sig was discoverer-emitted or hand-curated; with sig
gone, the markers carry no signal either.

Default mode prints a per-bank report. --apply rewrites the cfgs in
byte mode (CRLF-preserving). Lines that don't start with `func` or
`name` are untouched, as are comments other than the bare AUTO/MANUAL
marker (e.g. `# AUDIT_FIX:` annotations stay).

When a marker has prose attached (e.g. `# MANUAL — ROM body does
INX INX at entry`), the marker word is dropped and the prose is
preserved as a bare `# <prose>` trailing comment.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

_SIG_RE = re.compile(rb"\s+sig:\S+")
_MARKER_RE = re.compile(rb"^(AUTO|MANUAL)\b(.*)$", re.DOTALL)
_LEAD_SEP_RE = re.compile(rb"^[;,\-\xe2\x80\x94]+\s*")  # ; , - or em-dash bytes
_BANK_RE = re.compile(r"bank([0-9a-fA-F]+)\.cfg$")


@dataclass
class BankCounts:
    func_sig: int = 0
    name_sig: int = 0
    bare_auto: int = 0
    bare_manual: int = 0
    prose_auto: int = 0
    prose_manual: int = 0
    lines_mutated: int = 0


@dataclass
class StripResult:
    new_line: bytes
    sig_stripped: int = 0
    marker: Optional[str] = None
    marker_had_prose: bool = False
    head: Optional[bytes] = None


def _strip_line(line: bytes) -> StripResult:
    eol = b""
    body = line
    if body.endswith(b"\r\n"):
        eol = b"\r\n"
        body = body[:-2]
    elif body.endswith(b"\n"):
        eol = b"\n"
        body = body[:-1]

    stripped = body.lstrip()
    head: Optional[bytes] = None
    if stripped.startswith(b"func "):
        head = b"func"
    elif stripped.startswith(b"name "):
        head = b"name"
    else:
        return StripResult(new_line=line)

    hash_idx = body.find(b"#")
    if hash_idx >= 0:
        code = body[:hash_idx]
        comment_text = body[hash_idx + 1:]
    else:
        code = body
        comment_text = None

    code_new, sig_count = _SIG_RE.subn(b"", code)

    marker: Optional[str] = None
    marker_had_prose = False
    new_comment_segment: Optional[bytes] = None
    preserve_comment = False
    if comment_text is not None:
        stripped_cmt = comment_text.lstrip()
        m = _MARKER_RE.match(stripped_cmt)
        if m:
            marker = m.group(1).decode("ascii")
            rest = m.group(2).lstrip(b" \t")
            rest = _LEAD_SEP_RE.sub(b"", rest)
            if rest.strip():
                marker_had_prose = True
                new_comment_segment = b"# " + rest.rstrip()
            else:
                new_comment_segment = b""
        else:
            preserve_comment = True

    if sig_count == 0 and marker is None:
        return StripResult(new_line=line, head=head)

    code_new = code_new.rstrip(b" \t")
    if preserve_comment:
        out = code_new + b"  #" + comment_text.rstrip()
    elif new_comment_segment:
        out = code_new + b"  " + new_comment_segment
    else:
        out = code_new

    return StripResult(
        new_line=out + eol,
        sig_stripped=sig_count,
        marker=marker,
        marker_had_prose=marker_had_prose,
        head=head,
    )


def _process_bank(path: pathlib.Path, apply: bool) -> BankCounts:
    counts = BankCounts()
    raw = path.read_bytes()
    out_chunks = []
    for line in raw.splitlines(keepends=True):
        r = _strip_line(line)
        if r.sig_stripped == 0 and r.marker is None:
            out_chunks.append(line)
            continue
        counts.lines_mutated += 1
        if r.sig_stripped:
            if r.head == b"func":
                counts.func_sig += r.sig_stripped
            else:
                counts.name_sig += r.sig_stripped
        if r.marker == "AUTO":
            if r.marker_had_prose:
                counts.prose_auto += 1
            else:
                counts.bare_auto += 1
        elif r.marker == "MANUAL":
            if r.marker_had_prose:
                counts.prose_manual += 1
            else:
                counts.bare_manual += 1
        out_chunks.append(r.new_line)
    if apply and counts.lines_mutated:
        path.write_bytes(b"".join(out_chunks))
    return counts


def _format_report(per_bank: dict[str, BankCounts]) -> str:
    lines = ["# audit_func_sig_strip — report", ""]
    lines.append("v2 codegen ignores `sig:` entirely; the `# AUTO`/`# MANUAL`")
    lines.append("markers were v1-era provenance tags. Both are safe to strip.")
    lines.append("")
    lines.append("| Bank | Lines mutated | sig: (func) | sig: (name) | bare AUTO | bare MANUAL | AUTO + prose | MANUAL + prose |")
    lines.append("|------|---------------|-------------|-------------|-----------|-------------|--------------|----------------|")
    totals = BankCounts()
    for bank in sorted(per_bank):
        c = per_bank[bank]
        lines.append(
            f"| {bank} | {c.lines_mutated} | {c.func_sig} | {c.name_sig} | "
            f"{c.bare_auto} | {c.bare_manual} | {c.prose_auto} | {c.prose_manual} |"
        )
        totals.lines_mutated += c.lines_mutated
        totals.func_sig += c.func_sig
        totals.name_sig += c.name_sig
        totals.bare_auto += c.bare_auto
        totals.bare_manual += c.bare_manual
        totals.prose_auto += c.prose_auto
        totals.prose_manual += c.prose_manual
    lines.append(
        f"| **TOTAL** | **{totals.lines_mutated}** | **{totals.func_sig}** | "
        f"**{totals.name_sig}** | **{totals.bare_auto}** | "
        f"**{totals.bare_manual}** | **{totals.prose_auto}** | "
        f"**{totals.prose_manual}** |"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cfg-dir", default="recomp")
    p.add_argument(
        "--out",
        default="tools/audit_func_sig_strip_report.md",
    )
    p.add_argument("--apply", action="store_true",
                   help="Rewrite cfg files (default = report only)")
    args = p.parse_args()

    cfg_dir = pathlib.Path(args.cfg_dir)
    per_bank: dict[str, BankCounts] = {}
    for cfg_path in sorted(cfg_dir.glob("bank*.cfg")):
        m = _BANK_RE.search(cfg_path.name)
        if not m:
            continue
        counts = _process_bank(cfg_path, apply=args.apply)
        per_bank[cfg_path.name] = counts

    report = _format_report(per_bank)
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    print(report)
    if not args.apply:
        print("Report-only. Re-run with --apply to rewrite cfg files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
