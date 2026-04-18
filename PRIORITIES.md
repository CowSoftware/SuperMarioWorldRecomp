# Priorities

North star: **all-native-code execution of stock SMW**. Every hand-written
body in `src/smw_*.c` is a gotcha waiting to happen — divergence from the
ROM, wrong calling convention, silent behavior drift. The recompiler is
the only authoritative translator; every line we can retire to gen is a
line we can't have a bug in.

Work is tracked top-to-bottom. Complete a tier before starting the next.
Within a tier, commit after each landing so rollback is cheap.

---

## Done

- **Issue A — dispatch_known_addrs in augment pass**. `recomp.py` no longer
  decodes dispatch-handler bodies into the caller's insn list during
  `_augment_cfg_sigs_one_pass`, cutting phantom live-in cascade. Shipped
  with `test_decode_func_terminates_dispatch_when_all_handlers_known`.
- **Option 1 — SMW_DISABLE_LM compile-time toggle**. `HAS_LM_FEATURE(i)`
  and `HAS_HACK(i)` collapse to `0` when `SMW_DISABLE_LM` is defined
  (default ON in all four vcxproj configs). MSVC dead-codes the Lunar
  Magic emulation layer out of the binary. Undefining the macro restores
  LM-patched-ROM support.

## Active: skip elimination (→ all-native)

Drive every active `skip` entry in `recomp/bank*.cfg` to deletion by
teaching the recompiler whatever it's missing. Procedure for each:

1. Remove the `skip` line from cfg
2. Regen bank, build
3. If build fails or gen body disagrees with SMWDisX → fix the recompiler
   (framework fix, shipped with test per rule 1b)
4. Delete the hand-written body from `src/smw_*.c`
5. Regen, build, verify runtime parity past prior frame baseline
6. Commit

Attack order (easy → hard, smallest banks first to surface recompiler
gaps cheaply):

| Tier | Bank | Skip count | Rationale                                           |
|------|------|------------|-----------------------------------------------------|
| 1    | 0c   | 2          | `auto_0CADCA`, `auto_0CADD6` — credits/ending only  |
| 2    | 02   | 3          | `HandleExtendedSpriteLevelCollision`, Spr0A3 ×2     |
| 3    | 01   | 6          | Unused data table + collision/sprite hand bodies    |
| 4    | 03   | 27         | Mode-7, Bowser, Peach, SubOffscreen, sprite-vs-sprite |

Bank 03 is saved for last because it contains the densest 65816 tricks
(mode-7 transforms, PLX-as-return-addr, multi-entry sprite handlers,
inline data tables). Each gap fixed in earlier tiers chips away at
what's required for bank 03.

### Skip classification (bank 01, 02, 03)

- **bank 01/6**: 1 legitimate unreachable-dispatch-target stub
  (`Spr036_Unused_DataTable` — the ROM's CallSpriteMain dispatch table
  literally has `dw DATA_01E41F` for sprite $36; if that sprite were
  ever spawned the ROM would JSR into data. Current no-op stub is the
  safest treatment. Rule-0-compatible: we emit what the ROM does
  without pretending the target is real code). The other 5 bank 01
  skips are struct-return blocked.
- **bank 02/3**: all struct-return blocked.
- **bank 03/27**: mix of true stubs (Peach/Bowser battle endings,
  `{ return 0; }` placeholders that were never implemented — direct
  rule -1 violations to clean up), struct-return blockers (SubOffscreen,
  sprite-vs-sprite collision), carry-merge-at-branch
  (Spr0BD_SlidingNakedBlueKoopa), RTS-twice (Spr0A0_ActivateBowser
  Battle_ReturnsTwice_*), and mode-7 handlers. Triage needed to sort.

### Known blocker: struct-return override for stale hand bodies

When a cfg un-skips a function that previously had a hand-written
wrapper returning a struct (PointU8, RetAY, CheckPlatformCollRet) but
the ROM body actually returns void, the existing reconciliation keeps
the struct in funcs.h. Callers then mismatch the void gen body.

A naive framework fix (let cfg `sig:void(...)` override funcs.h struct
returns the same way it already overrides pointer returns) is too
broad: multiple functions carry divergent sigs across banks (e.g.
`FindFreeNormalSpriteSlot_HighPriority` has `sig:RetAY()` in bank01,
`sig:void()` in bank02, `sig:uint8()` in bank03). A blanket override
picks the wrong winner.

Real fix options (pick when we're ready):
1. **Cross-bank sig reconciliation pass**: pick one sig per function
   based on aggregate usage (all caller sites' expected return type).
   More work; affects the whole sig pipeline.
2. **Opt-in `force_sig ADDR SIG` cfg directive**: unconditional override
   for exactly the listed address. Parser + reconcile change; ~30 min.
3. **Per-function `override_ret` flag on the `sig:` token**: e.g.
   `sig:void(uint8_k) override`. Cleanest UX, same work as option 2.

Tier 2 (bank 02) and tier 3's struct-return entries (CheckTiltingPlatform
Collision, Spr0A3, Spr0A7, Spr05F) all need this before the skips
can drop cleanly. Recommend option 3 when we pick it up.

## Parallel track: SMWDisX conformance harness

Goal: mechanical per-function pass/fail comparison of our decoded
65816 instruction stream against SMWDisX's human-verified one. Turn
the spot-check against `SMWDisX/bank_XX.asm` that we do by hand into
a continuous regression gate.

MVP (v0.1): parse SMWDisX to extract per-address code/data classification
and per-function instruction mnemonics; decode the same addresses
via `snesrecomp.recomp.decode_func`; report mismatches. Starts with
the dominant failure class — **our decoder walked into SMWDisX-labeled
data** — and grows from there.

Lives at `tools/smwdisx_compare.py`. Not a blocker for skip-elimination;
surfaces which functions need recompiler work.

Growth plan:
- v0.1: code-vs-data boundary check (decode_into_data errors)
- v0.2: per-instruction mnemonic + operand parity
- v0.3: M/X state tracking
- v0.4: macro + conditional-assembly handling (U ROM branch only)
- v0.5: repo-wide pass-rate dashboard in CI

## Queued: warning elimination (after skips)

- **Issue B — FuncU8J / FuncU8A / FuncU8JA union-sig dispatch**. Current
  dispatch-target guard at `recomp.py:1627` caps `FuncU8*` handlers to
  `void()` or `void(uint8 k)`. Collect dispatch targets, compute union
  live-in across handlers, widen all handlers in each table to the
  union sig, emit matching cast type. Target: the remaining
  `RECOMP_WARN: X/A/j unknown at call site` warnings collapse.
  Typedef family goes in `snesrecomp/runner/src/types.h`.

- **Live-in rescue for mid-body PH/PL scribble-restore pattern**. When
  `…PHX ; TYX ; JSL ; PLX ; <read X>` appears mid-body, entry-X is
  legitimately live-in but current `_insn_reg_use` (recomp.py:499)
  doesn't detect it because it intentionally skips PH/PL as register
  reads. Only pursue if skip-elimination surfaces false narrowings.

## Hard rules in force

See `CLAUDE.md`. Key ones for this priority list:

- Recompiler is the authority; cfg is last-resort for things not
  derivable from ROM (rule 0). Each skip removed that doesn't come
  back is a recompiler fact gained.
- SMWDisX is the primary literal-code oracle (session start rule 3).
- No stubs, placeholders, compat shims (rule -1).
- Tests ship with framework changes (rule 1b).
- Generated files never hand-edited: `src/gen/*_gen.c`, `recomp/funcs.h`
  (auto-block only — preamble is preserved/hand-maintained),
  `src/gen/bank_range.h` (rule 7).
- Commit snesrecomp first when framework changes; SMW commit references
  the snesrecomp SHA.
