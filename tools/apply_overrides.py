#!/usr/bin/env python3
"""Apply the optional override layer to freshly generated banks.

Runs at build time, AFTER snesrecomp emits src/gen/ and BEFORE compilation.
For each rule in a manifest it injects an idempotent, runtime-gated dispatch
prologue into the matching generated function(s), so the override layer
survives regeneration without anyone hand-editing src/gen/.

See overrides/README.md for the full design and the contract override bodies
must follow.

Usage:
    python tools/apply_overrides.py [--gen-dir src/gen]
        [--manifest overrides/widescreen/overrides.manifest] [--check] [-v]

With no manifest rules active this is a no-op (authentic build). Safe to run
on every build: injection is marked and skipped if already present.
"""
import argparse
import os
import re
import sys

MARKER = "/*WS-OVERRIDE*/"

# Matches a generated function DEFINITION (opening brace), not a forward
# declaration (which ends in ';'). Captures the base name and the _M?X? suffix.
#   RecompReturn  SomeName_M1X1 ( CpuState *cpu ) {
DEF_RE = re.compile(
    r"^RecompReturn\s+([A-Za-z_][A-Za-z0-9_]*?)(_M[01]X[01])\s*"
    r"\(\s*CpuState\s*\*\s*cpu\s*\)\s*\{",
    re.MULTILINE,
)


def parse_manifest(path):
    """Return list of (base_name, override_symbol, variant_or_None)."""
    rules = []
    if not os.path.isfile(path):
        return rules
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "->" not in line:
                sys.exit(f"apply_overrides: malformed manifest line: {raw!r}")
            lhs, rhs = line.split("->", 1)
            base = lhs.strip()
            parts = rhs.split()
            override = parts[0].strip()
            variant = parts[1].strip() if len(parts) > 1 else None
            rules.append((base, override, variant))
    return rules


def prologue(override_symbol):
    return (
        f" {MARKER} {{ extern bool g_ws_active;"
        f" extern RecompReturn {override_symbol}(CpuState *cpu);"
        f" if (g_ws_active) return {override_symbol}(cpu); }}"
    )


def apply_to_text(text, rules):
    """Return (new_text, n_injected). Idempotent."""
    by_base = {}
    for base, override, variant in rules:
        by_base.setdefault(base, []).append((override, variant))

    injected = 0

    def repl(m):
        nonlocal injected
        whole = m.group(0)
        base, suffix = m.group(1), m.group(2)
        cands = by_base.get(base)
        if not cands:
            return whole
        # Pick a rule whose variant matches this definition (or is unscoped).
        chosen = None
        for override, variant in cands:
            if variant is None or variant == suffix[1:]:  # suffix like '_M1X1'
                chosen = override
                break
        if chosen is None:
            return whole
        if MARKER in whole:  # already injected on a previous build
            return whole
        return whole + prologue(chosen)

    new_text = DEF_RE.sub(repl, text)
    # Count injections by counting freshly added markers vs pre-existing.
    return new_text, new_text.count(MARKER) - text.count(MARKER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-dir", default="src/gen")
    ap.add_argument(
        "--manifest", default="overrides/widescreen/overrides.manifest"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify every manifest base matched at least one definition",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    rules = parse_manifest(args.manifest)
    if not rules:
        if args.verbose:
            print("apply_overrides: no active rules — authentic build, no-op")
        return 0

    if not os.path.isdir(args.gen_dir):
        sys.exit(f"apply_overrides: gen dir not found: {args.gen_dir}")

    matched_bases = set()
    total = 0
    for name in sorted(os.listdir(args.gen_dir)):
        if not name.endswith(".c"):
            continue
        path = os.path.join(args.gen_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        # Track which bases exist in this file before substitution.
        for m in DEF_RE.finditer(text):
            if m.group(1) in {b for b, _, _ in rules}:
                matched_bases.add(m.group(1))
        new_text, n = apply_to_text(text, rules)
        if n:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            total += n
            if args.verbose:
                print(f"apply_overrides: {name}: injected {n}")

    if args.check:
        missing = {b for b, _, _ in rules} - matched_bases
        if missing:
            sys.exit(
                "apply_overrides: manifest bases never matched a definition: "
                + ", ".join(sorted(missing))
            )

    print(f"apply_overrides: injected {total} dispatch prologue(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
