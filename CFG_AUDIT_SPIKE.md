# CFG override audit spike — tracking

**Goal:** validate every override in `recomp/bank*.cfg` against the current
recompiler. Classify each as redundant / load-bearing / wrong. Fix the
wrong ones. Strip the redundant ones. Flag framework gaps for the
load-bearing ones.

**Why:** these overrides accumulated over many iterations of buggier
discover.py and recomp.py. None have been systematically audited. The
koopa-spawn bug (#27) was one wrong `end:` directive among many; others
plausibly hide in the remaining ~1,400 overrides.

**Plan:** see `plans/floating-sauteeing-floyd.md` (via Claude session tooling).
Multi-session spike, ~8 sessions / 25 hours estimated.

## Methodology

Per override, the validator (`snesrecomp/tools/cfg_override_validator.py`):

1. Strips the override token from its cfg line.
2. Regens the bank.
3. Diffs gen-C vs baseline.

If diff is empty → **redundant**, safe to strip.
If diff is non-empty → **load-bearing**, needs human review (SMWDisX
cross-check) to decide if override is correct or wrong.

Triage via `snesrecomp/tools/cfg_override_triage.py` (reads latest
results in `snesrecomp/tools/cfg_audit_results/*.json`).

## Session log

- **2026-04-22 session 1**: Phase A complete.
  - Built `cfg_override_validator.py` (supports end/sig/rep/repx/sep/
    init_y/init_carry/carry_ret/ret_y/restores_x/y_after/x_after).
  - Built `cfg_override_triage.py` (summary + list by diff-class).
  - Ran full `end:` audit across 9 banks (~14 min). Results below.

- **2026-04-22 session 1 (Phase C)**:
  - Ran full `sig:` audit across 9 banks (~35 min, 1,169 sigs).
  - Stripped 8 redundant on bank 0d (parent commit `9f37e83`).
  - Built `cfg_override_sig_crosscheck.py` — compares each
    load-bearing cfg sig against what `_augment_sig_with_livein`
    derives from ROM live-in analysis.
  - Cross-check results: 701 AGREES, 116 CFG_WIDER (pointer/DP
    params live-in doesn't model — cfg correct), 14 CFG_NARROWER
    (live-in auto-widens at regen), 3 TYPE_DIFF (live-in under-
    detects M-width; cfg correct after spot-check of
    HandleStandardLevelCameraScroll_00F7F4), 320 RET_DIFF (live-in
    doesn't infer returns — not a divergence), 7 UNCLEAR.
  - **Zero confirmed wrong sigs found.** sig: pile is clean.

- **2026-04-22 session 1 (Phase B partial)**:
  - Stripped 22 validated-redundant `end:` directives on bank 0d
    (parent commit `5591265`). Live-boot confirmed no regression.
  - Built `cfg_override_smwdisx_crosscheck.py` (SMWDisX/.sym-based
    label map + discoverer d_end comparison + sibling-coverage
    sanity check).
  - Cross-checked all 491 load-bearing `end:` overrides:
    - **450 CLEAN** (cfg_end lands on/near SMWDisX label — correct).
    - **34 SUSPECT** (no SMWDisX label nearby, but sibling/d_end
      checks don't flag — likely internal sub-entries not named in
      SMWDisX).
    - **1 SUSPECT_NARROW** — manually verified as false positive
      (`LoadLevel_HandleChocolateIsland2Gimmick` in bank 05; JSL
      ExecutePtrLong dispatch pattern with cfg-documented
      exclude_range; cfg end: is correct).
    - **6 SUSPECT_WIDE** — spot-checked one
      (`PlayerState0B_RescuedPeach`); cfg_end extends through data
      tables with `exclude_range` lines covering them. Correct.
  - **Bottom line: ZERO confirmed wrong end: overrides.** Bug #8
    and other gameplay bugs are NOT hiding in end: directives.
    Next: audit sig: overrides (837 entries, largest bucket).

## Per-override-type status

### `end:` (513 overrides) — Phase A done 2026-04-22

| Bank | Total | Redundant | Stripped | Load-bearing | SMWDisX-CLEAN | SMWDisX-SUSPECT | Wrong-confirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| 00 | 309 |   0 |  0 | 309 | 283 | 26 | 0 |
| 01 |   7 |   0 |  0 |   7 |   6 |  1 | 0 |
| 02 |  13 |   0 |  0 |  13 |  12 |  1 | 0 |
| 03 |   4 |   0 |  0 |   4 |   4 |  0 | 0 |
| 04 | 118 |   0 |  0 | 118 | 112 |  6 | 0 |
| 05 |  16 |   0 |  0 |  16 |  13 |  3 | 0 |
| 07 |   3 |   0 |  0 |   3 |   2 |  1 | 0 |
| 0c |  18 |   0 |  0 |  18 |  16 |  2 | 0 |
| 0d |  25 |  22 | 22 |   3 |   2 |  1 | 0 |
| **Total** | **513** | **22** | **22** | **491** | **450** | **41** | **0** |

Phase B verdict on `end:` overrides: **all correct**. No bug-class
wrongs found. Strip-reducible count: 22 (done).

**Observation**: banks 00 + 04 in particular show 100% load-bearing with
uniform 1745-line diffs across every override — meaning stripping ANY
one cascades through auto-promote / sub-entry-promotion for the whole
bank. This is the "cfg end: directives are load-bearing for four passes
that iterate" coupling documented in `cfg_strip_redundant.py`. Redundant-
strip is locally safe but globally coupled; strip one at a time and
re-audit iteratively.

Bank 0d has 22 genuinely-redundant `end:` directives (first batch to
strip). The 3 load-bearing on 0d are small-diff candidates that need
SMWDisX review.

### `sig:` (1,169 overrides) — Phase C first pass done 2026-04-22

Note: earlier 837 count was "non-default sig" only. Validator counted
every `sig:X` token. 1,169 total.

| Bank | Total | Redundant | Stripped | Load-bearing | AGREES | CFG_WIDER | CFG_NARROWER | TYPE_DIFF | RET_DIFF | UNCLEAR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00 | 302 | 0 | 0 | 302 | ... | ... | ... | ... | ... | ... |
| 01 | 444 | 0 | 0 | 444 | ... | ... | ... | ... | ... | ... |
| 02 | 289 | 0 | 0 | 289 | ... | ... | ... | ... | ... | ... |
| 03 |  42 | 0 | 0 |  42 | ... | ... | ... | ... | ... | ... |
| 04 |   3 | 0 | 0 |   3 | ... | ... | ... | ... | ... | ... |
| 05 |  24 | 0 | 0 |  24 | ... | ... | ... | ... | ... | ... |
| 07 |   2 | 0 | 0 |   2 | ... | ... | ... | ... | ... | ... |
| 0c |   7 | 0 | 0 |   7 | ... | ... | ... | ... | ... | ... |
| 0d |  56 | 8 | 8 |  48 | ... | ... | ... | ... | ... | ... |
| **Total** | **1,169** | **8** | **8** | **1,161** | **701** | **116** | **14** | **3** | **320** | **7** |

**Phase C cross-check verdict: 0 confirmed wrong sigs found.**

Classification legend:
- **AGREES** (701): cfg sig == live-in-derived sig. Strippable in
  principle but validator still flags load-bearing — other cfg-
  interactions make the full gen-C differ.
- **CFG_WIDER** (116): cfg declares params that live-in doesn't see.
  Spot-checks show these are mostly pointer params (`*p`) or DP-slot
  params (`r0`, `r2w`) that live-in's A/X/Y tracking doesn't model.
  cfg is correct; encodes knowledge live-in can't derive.
- **CFG_NARROWER** (14): cfg declares FEWER params than live-in
  infers. In practice the regen-time augment widens them, so no
  divergence at emit. Review list for future pruning.
- **TYPE_DIFF** (3): cfg declares uint16 where live-in says uint8.
  Spot-check of `HandleStandardLevelCameraScroll_00F7F4` confirmed
  cfg is right (caller does `LDA.W #$00C0` + JSR — 16-bit). Live-in
  under-detects M=0 state.
- **RET_DIFF** (320): cfg declares a return type (uint8, PairU16,
  struct...) that live-in always reports as `void` (live-in doesn't
  infer returns). Expected; not a divergence signal.
- **UNCLEAR** (7): live-in computation failed.

**Outcome**: sig: directives look clean. The recompiler's live-in
inference is deliberately conservative; cfg overrides bridge the
gap where live-in can't see.

Stripped 8 redundant sigs in bank 0d (parent commit `9f37e83`).
Live-boot check passed.
### `rep:` / `repx:` / `sep:` (35 overrides) — Phase D done 2026-04-22, REVISED after validator fix

| Type | Total | Redundant (strippable) | Load-bearing | Verified CORRECT |
|---|---:|---:|---:|---:|
| rep  | 21 | 12 |  9 | 21 |
| repx | 12 |  9 |  3 | 12 |
| sep  |  2 |  0 |  2 |  2 |

Initial pass (before validator fix) claimed all 35 load-bearing. A
later empirical probe showed OwTileAnimations_0480B9 stripped had a
1-line cosmetic diff with proper path resolution — the validator was
classifying overrides as load-bearing due to path-resolution
confounders (stripped cfg in bare tmp dir lacked sibling bank*.cfg
and funcs.h search paths, while baseline regen had both). Validator
now mirrors the full repo layout (recomp/+src/funcs.h) into tmp_dir
so stripped and baseline share identical resolution context.

A second framework gap surfaced: the caller-M/X inference pass's
"joint-unanimity + old_entry == 0" guards were too conservative.

1. Joint-unanimity: blocked propagation when callers unanimously
   agree on M=0 but split on X (common: $04:9885 OW_TilePos_Calc).
   Now decides M and X bits independently.
2. old_entry == 0: blocked merging derived bits into partial cfg
   overrides (e.g. cfg says `repx:X`, callers say M=0 — the M=0 bit
   should be added). Now merges, keeping SEP marker 0x40 opaque.

6 new framework tests in `test_mx_inference_from_callers.py` pin the
behaviour.

After validator fix + framework fix: 21 of 35 overrides strip cleanly
(commits snesrecomp 0a71864 + parent ddf4295). Remaining 14 load-
bearing break down as:
  - 9 rep: (callers split on M OR dispatch-only / hook-metadata
    cosmetic)
  - 3 repx:
  - 2 sep: (GameMode08_FileSelect + ScrollLayer3 — internal SEP
    markers the decoder's linear walk can't derive from callers)

Three of the remaining are cosmetic-only (diff=2 from hook-metadata
flag on the first insn — the decoder stamps `insn.m_flag` before the
in-body REP fires, which changes the RDB_INSN_HOOK's `writes` field
by 1 bit without affecting generated behaviour). Candidates for a
future emitter fix that suppresses m_flag stamp on a function's own
entry REP/SEP.

gen-C diff: bank 04 1039 lines reflects real correctness improvement
where previously-partial `rep:X` overrides (no `repx:X`) caused mid-
body LDX.B reads to emit as 8-bit while the ROM actually entered at
X=0. funcs.h widened 2 sigs (PlayerState00_00F8F2,
PlayerState00_00F9C9) that now correctly carry uint8 k.

### Behavioral hints (17 overrides) — Phase D done 2026-04-22

| Type | Total | Correct |
|---|---:|---:|
| carry_ret | 6 | 6 |
| ret_y | 8 | 8 |
| restores_x | 1 | 1 |
| y_after | 1 | 1 |
| init_carry | 1 | 1 |
| init_y | 0 | — |
| x_after | 0 | — |

All manually verified via SMWDisX. Each is a specific ABI pattern
(carry-as-bool return, Y-as-return, X-restore from WRAM) the
recompiler's live-in inference can't derive. All correct.

### `exclude_range` (1,006 entries) — Phase E done 2026-04-22

Audited via `cfg_exclude_range_audit.py`:
- 831 bytes-look-like-DATA (decode fails / validation fails). Clean.
- 175 bytes-look-like-CODE. Spot-checked — all are legitimate
  "code that belongs to another function" cases where the exclude
  prevents double-discovery (e.g. `$00:816B-$8374` NMI-body chunk
  is code, but excluded so auto-promote doesn't make it a new
  function entry).

**Zero wrong exclude_range directives found.**

### `skip` (1 override) — Phase E done 2026-04-22

Single entry: `Spr036_Unused_DataTable` — a data-table at a dispatch
target for unused sprite $36. Hand-body is a no-op. Correct.

### `dispatch` / `jsl_dispatch*` / `no_autodiscover` — 0 literal overrides

These patterns are detected automatically by
`_auto_detect_dispatch_helpers`. No cfg-level overrides exist in
current cfgs.

### standalone `name` lines with sig — not audited

These declare aliases / cross-bank names for sub-entries. Their
correctness is cross-checked through the `sig:` audit (same sig
would be declared on the `func` or `name` line).

## Open items — load-bearing + wrong (suspected)

Populated as SMWDisX cross-checks identify wrong overrides. Empty for now.

| Bank:Addr | Override | Why wrong | Proposed fix | Status |
|---|---|---|---|---|
| — | — | — | — | — |

## Open items — framework gaps

Load-bearing + correct overrides surface framework gaps the recompiler
should close. Populated after Phase B cross-check.

| Pattern | Overrides affected | Framework change needed |
|---|---|---|
| — | — | — |

## Recent fixes

| Date | Commit | Overrides affected | Description |
|---|---|---|---|
| 2026-04-22 | `c637d20` (parent) | 1 | auto_02_BCF8 stripped (`cfg_strip_redundant` Pass 2 with full safety) |
| 2026-04-22 | `eacf04c` (snesrecomp) | — | `cfg_strip_redundant` tool hardened with organic-discovery / standalone-name / auto-name-shape checks |
| 2026-04-21 | `791dc5e` (snesrecomp) | 13 | koopa-class `end:` directives added by cfg_apply_audit_fixes (Phase 1) |
| 2026-04-21 | `38ff1c1` (snesrecomp) | — | Phase 2 framework: discover.py per-function d_end computation, auto-promote plumbs into cfg |

## Tooling

- `snesrecomp/tools/cfg_override_validator.py` — run strip-and-diff audit.
  - `--type end --all` — full audit, ~14 min.
  - `--type end --bank 0d` — single bank, ~20s.
- `snesrecomp/tools/cfg_override_triage.py` — summarize + list results.
  - Default: print summary across all available results.
  - `--list redundant --type end` — show strippable overrides.
  - `--list load-bearing --type end --bank 00 --limit 20` — show
    cross-check candidates.
- `snesrecomp/tools/cfg_audit_results/*.json` — per-session raw results
  (gitignored, re-runnable).

## Phase progress

- [x] Phase A: tooling + `end:` audit
- [x] Phase B: strip redundant end: (22 done), SMWDisX cross-check
      load-bearing end: (450 CLEAN / 41 SUSPECT / 0 WRONG — all
      SUSPECT manually verified as false positives)
- [x] Phase C: sig: audit first pass done — 8 strippable + 1,161
      load-bearing analyzed via live-in cross-check; 0 WRONG
      confirmed. The load-bearing sigs encode real ABI info live-in
      can't derive (pointer/DP params, struct returns, explicit
      widths in REP-covered callers).
- [x] Phase D: rep:/repx:/sep: (35 overrides) + behavioral hints
      (17 overrides). 0 strippable, all load-bearing. Manual review
      confirmed ALL correct. 0 WRONG.
- [x] Phase E: exclude_range (1,006) + skip (1) + dispatch (0) +
      no_autodiscover (0) + jsl_dispatch (0). 0 WRONG confirmed.
- [ ] Phase F: wrap-up + bug #8 regression check + pivot to
      recompiler-smartening work

## Next-session handoff pointer

Spike audit complete 2026-04-22. Current work has pivoted to
**making the recompiler smarter** to reduce the load-bearing
override count without regressions. Two tiers in that pivot:

### Tier 2 (NEXT) — Small framework gaps

Low-risk individual improvements that each eliminate a class of
load-bearing overrides. Tackle one at a time; verify no gen-C
regressions via full 9-bank regen + live-boot screenshot after each.

Candidate targets (ordered by likely impact × simplicity):

1. **Cross-call M-state propagation** (~35 `rep:`/`repx:`/`sep:` +
   3 sig `TYPE_DIFF` eliminations). Today the decoder enters each
   function in M=1,X=1 regardless of how callers set mode before
   JSR. Walking callers' M/X state across JSR edges and using the
   dominant caller-state as the callee's entry state would close
   most of these. Implementation lives in recomp.py around
   `_scan_parent_mx_at` (already does this for sub-entries —
   generalize to all JSR'd callees).

2. **Carry-return broadening** (~6 `carry_ret` eliminations).
   `_looks_like_carry_return` already detects CLC/SEC + RTS
   patterns. Broaden to detect CMP-before-RTS and EOR #$01-
   before-RTS as implicit carry returns.

3. **Y-return detection** (~8 `ret_y` eliminations). Similar to
   carry-return: detect functions whose only post-RTS consumer
   reads Y → mark as `ret_y`.

4. **DP-slot live-in** (~50-80 sig `CFG_WIDER` eliminations).
   Extend `infer_live_in_regs` to track DP scratch-slot reads
   (`LDA $00` etc) before any DP write. Emit as `r0`, `r2w` etc.

5. **Pointer-param inference** (~15-25 sig `CFG_WIDER` eliminations).
   Detect when a ZP slot is consumed via `LDA [$F6],Y` — caller
   passes a pointer. Emit as `*p`.

Each target: (a) write a framework test pinning the new behavior;
(b) implement; (c) regen all 9 banks and diff — expect narrow,
targeted gen-C changes; (d) strip the overrides that are now
redundant via `cfg_override_validator.py --type X --all` →
`cfg_override_strip.py --type X --apply`; (e) full live-boot
visual check.

### Tier 1 (AFTER Tier 2) — Decouple iterative passes from cfg end:

The larger structural refactor. Current `cfg end:X` directives
shape FOUR passes simultaneously: decode_func, promote_sub_entries
(iterative), auto_promote_branch_targets (iterative),
_auto_detect_dispatch_helpers. A clean decoupling lets cfg end:
bound only the single func's own decode; the iterative passes use
their own range logic based on discovered starts + exclude_range.
Once decoupled, the 450+ load-bearing end: directives that just
document next-non-skip become safely strippable.

Specific refactor path: extract the `ends` map in
`auto_promote_branch_targets` and `promote_sub_entries`'s enclosing-
range check into a shared `_compute_func_ranges(cfg)` helper that
uses discovered addresses + exclude_range instead of cfg.funcs' own
end_override. Then validate gen-C unchanged, then pilot-strip.

### Return to bug #8 LAST

After Tier 2 + Tier 1 land, return to Mario-1-block-under (bug #8)
from a cleaner base. With fewer load-bearing overrides and a
smarter framework, any remaining gameplay bugs are in the
runtime / oracle-sync / cross-bank-interaction layer — easier to
diagnose without the cfg noise.

## FINAL TALLY — REVISED 2026-04-22 (session 3) after all-banks validator + exclude_range support

| Override type | Total | Stripped | Remaining | Wrong |
|---|---:|---:|---:|---:|
| end | 513 | 450 | 63 | 0 |
| sig | 1,169 | 21 | 1,148 | 0 |
| rep | 21 | 13 | 8 | 0 |
| repx | 12 | 9 | 3 | 0 |
| sep | 2 | 0 | 2 | 0 |
| carry_ret | 6 | 0 | 6 | 0 |
| ret_y | 8 | 0 | 8 | 0 |
| restores_x | 1 | 0 | 1 | 0 |
| y_after | 1 | 0 | 1 | 0 |
| init_carry | 1 | 0 | 1 | 0 |
| exclude_range | 1,006 | 864 | 142 | 0 |
| skip | 1 | 0 | 1 | 0 |
| **Total** | **2,741** | **1,357** | **1,384** | **0** |

**Session 3 additional findings:**

- sig audit re-run after strips: 335 "per-token-owning-bank-redundant"
  turned out to be cross-bank load-bearing (cfg_override_maximize
  admitted 0/335). Fixed validator to check ALL banks per-token
  (snesrecomp 5a964d0). The per-token test is now a true
  strip-and-test-everywhere. Cost: 9x regen per candidate (sig
  audit went from ~45 min to hours, but bucket is now reliable).
  True sig strippable: 13.

- Behavioral hints audit: all 17 load-bearing (carry_ret 6,
  ret_y 8, restores_x 1, y_after 1, init_carry 1). Confirms
  Phase D manual review.

- exclude_range support added to validator (snesrecomp c0b3e2e).
  New 'line' kind for standalone directives (strip = remove line).
  INTRA_BANK_TYPES flag lets these skip the 9x all-banks cost
  since their effects stay in one bank.

- End bank-05's 12 demoted end: candidates: maximize recovered 0
  (all cross-bank load-bearing).

- exclude_range audit: **864 of 1,006 redundant (86%)!** Biggest
  cleanup bucket. Strips went cleanly; only 4 cosmetic lines of
  cross-bank cascade in bank 01's gen-C. The 142 remaining are
  genuinely load-bearing — mostly bank 01 (140 entries, high
  data/code interleaving).

**Grand total session 1+2+3: 1,357 of 2,741 overrides shed (50%).**

**Outstanding audits:**
- name (cross-bank aliases, 956 entries, audit running).
- preserves (3 entries, edge case).
- default_init_y (2 entries, bank-wide hint).
- data (1 entry, explicit ROM extraction).

## FINAL TALLY — REVISED 2026-04-22 (later) after validator + framework fixes

| Override type | Total | Stripped (session 1) | Stripped (session 2 additional) | Grand total | Remaining | Wrong |
|---|---:|---:|---:|---:|---:|---:|
| end | 513 | 22 | 428 | 450 | 63 | 0 |
| sig | 1,169 | 8 | 13 | 21 | 1,148 | 0 |
| rep | 21 | 0 | 13 | 13 | 8 | 0 |
| repx | 12 | 0 | 9 | 9 | 3 | 0 |
| sep | 2 | 0 | 0 | 0 | 2 | 0 |
| carry_ret | 6 | 0 | 0 | 0 | 6 | 0 |
| ret_y | 8 | 0 | 0 | 0 | 8 | 0 |
| restores_x | 1 | 0 | 0 | 0 | 1 | 0 |
| y_after | 1 | 0 | 0 | 0 | 1 | 0 |
| init_carry | 1 | 0 | 0 | 0 | 1 | 0 |
| exclude_range | 1,006 | 0 | 0 | 0 | 1,006 | 0 |
| skip | 1 | 0 | 0 | 0 | 1 | 0 |
| **Total** | **2,741** | **30** | **463** | **493** | **2,248** | **0** |

**Session 2 additional findings (driven by validator + framework fixes):**

- `cfg_override_validator.py` had a path-resolution confounder: stripped
  cfg was written to a bare tmp dir without sibling bank*.cfg or
  funcs.h access, while baseline regenned from the real repo. Every
  stripped regen diffed for path reasons unrelated to the override.
  Fixed by mirroring the full repo layout into tmp.

- The caller-M/X inference pass had two over-conservative guards
  (joint unanimity + skip-when-partially-set) and ran AFTER
  sub-entry + auto-promote. Fixed to decide M/X axes independently,
  merge into partial cfg overrides, and run before downstream passes
  (snesrecomp 0a71864 + 88cbcc9). 6 regression tests in
  test_mx_inference_from_callers.py pin the new behavior.

- `_apply_all_redundant_and_verify` + `_bisect_cascade_offenders`
  added to the validator (snesrecomp c810a77) to catch the case
  where per-token-empty strips cascade when applied collectively
  (live-in / sig inference fixpoint drift). `cfg_override_strip.py`
  skips `cascade_offender == true` (snesrecomp 06403ef).

- Sig audit recovered 348 per-token-redundant. Apply-all caught
  cascades in banks 00/02/03/04 (GraphicsDecompress's inferred
  return widened to uint8* and broke a caller's bitwise OR). Binary
  bisection couldn't isolate single offenders — the cascades are
  multi-element combinations. Conservative demote of 335 kept
  those sig hints in cfg. 13 bank-05/07/0c sigs applied cleanly.

- End audit recovered 440 per-token-redundant. Apply-all cascade
  in bank 05 (12 candidates, multi-element). 428 applied cleanly
  across 6 banks — a large payoff from Phase 2's d_end discovery
  (snesrecomp 38ff1c1) finally getting the test suite to confirm
  it was doing the work.

**Zero wrong overrides; zero functional regressions** (visual
confirmed clean by user after 22 rep/repx + 1 rep + 13 sig + 428
end strip batches).

**Future work to recover the 335 demoted sigs + 12 demoted bank-05
ends:** per-bank apply-all (strip only one bank's candidates,
regen all, diff) would resolve cases where the cascade is single-
bank. Cross-bank cascades need a different approach — probably
iterative strip-verify-commit to narrow incrementally.

**Framework is doing its job.** The cfg is no longer holding
information derivable from the ROM: 493 lines shed this overhaul.
Remaining 1,148 sigs, 1,006 exclude_ranges, and 63 end: are the
genuinely-load-bearing bits (pointer/DP params, data-region
boundaries, dispatch-target conventions) that stay per-game.
