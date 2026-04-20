#!/usr/bin/env python3
"""One-shot: cross-check kPatchedCarrys_SMW against exclude_range in bank cfgs.

Prints, for each of the 45 patch addresses:
  - bank
  - whether the bank is recompiled (has a recomp/bank*.cfg)
  - whether the address falls inside any exclude_range in that bank's cfg

If every address is in a recompiled bank AND outside all exclude_ranges,
the patch array is dead for runtime and can be ripped outright.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Pulled from src/smw_cpu_infra.c.
PATCH_ADDRS = [
    0xFE1F, 0xFE26, 0xFE35,
    0x1807a, 0x18081,
    0x1A2CC, 0x1B066,
    0x0fe79, 0x0fe80, 0x0fe88,
    0x1DDFB, 0x1E0DD,
    0x2AAFB, 0x2B05B, 0x2B0A2, 0x2B0A4, 0x2B1DD, 0x2B29B, 0x2B2F6,
    0x3AD9B, 0x498A2,
    0x2FBF5, 0x2FBF7, 0x2FC11, 0x2FC13, 0x2FC34, 0x2FBFA,
    0x1D021, 0x1D028,
    0x1B182, 0x1FDD6, 0x2B368, 0x2BB3E,
    0x2C061, 0x2C06C, 0x2AD15, 0x02DDA1,
    0x0399DB,
    0x1BC75, 0x1BC78, 0x1BC7A, 0x2B228,
    0x2f231, 0x2f23d, 0x2f245,
    0x3C073,
]


def load_excludes(bank: int):
    """Return list of (lo16, hi16) inclusive exclude ranges for a bank."""
    cfg = ROOT / "recomp" / f"bank{bank:02x}.cfg"
    if not cfg.exists():
        return None  # bank not recompiled
    ranges = []
    for line in cfg.read_text().splitlines():
        m = re.match(r"\s*exclude_range\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)", line)
        if m:
            ranges.append((int(m.group(1), 16), int(m.group(2), 16)))
    return ranges


def main():
    # Cache per-bank excludes.
    bank_cache = {}

    def get(bank):
        if bank not in bank_cache:
            bank_cache[bank] = load_excludes(bank)
        return bank_cache[bank]

    clean = []
    excluded = []
    unrecompiled = []

    for addr in PATCH_ADDRS:
        bank = addr >> 16
        local = addr & 0xFFFF
        excludes = get(bank)
        if excludes is None:
            unrecompiled.append((addr, bank))
            continue
        hit = None
        for lo, hi in excludes:
            if lo <= local <= hi:
                hit = (lo, hi)
                break
        if hit:
            excluded.append((addr, bank, hit))
        else:
            clean.append((addr, bank))

    print(f"Total patch entries: {len(PATCH_ADDRS)}")
    print(f"  Clean (recompiled, outside exclude_range): {len(clean)}")
    print(f"  Excluded (inside an exclude_range):        {len(excluded)}")
    print(f"  Unrecompiled bank:                         {len(unrecompiled)}")
    print()

    if excluded:
        print("EXCLUDED entries (interpreter-path, patch still live):")
        for addr, bank, (lo, hi) in excluded:
            print(f"  0x{addr:06X}  bank{bank:02x}  in exclude_range {lo:04X} {hi:04X}")
        print()

    if unrecompiled:
        print("UNRECOMPILED bank entries (interpreter-path, patch still live):")
        for addr, bank in unrecompiled:
            print(f"  0x{addr:06X}  bank{bank:02x} (no cfg)")
        print()

    if not excluded and not unrecompiled:
        print("VERDICT: all 45 patch addresses are in recompiled code outside all")
        print("exclude ranges. The kPatchedCarrys_SMW array is dead at runtime and")
        print("can be ripped.")
        return 0
    print("VERDICT: at least one patch address remains interpreter-reachable.")
    print("Cannot rip outright without addressing the flagged entries.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
