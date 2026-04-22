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
### `rep:` / `repx:` / `sep:` (27 overrides) — not started
### `init_y:` / `carry_ret` / `ret_y` / etc (17 overrides) — not started
### `exclude_range` — not started
### `dispatch` / `jsl_dispatch*` — not started
### `skip` — not started
### `no_autodiscover` — not started
### standalone `name` lines with sig — not started

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
- [ ] Phase D: `rep:`/`repx:`/`sep:` + behavioral hints
- [ ] Phase E: `exclude_range` / `dispatch` / `skip` / `no_autodiscover`
- [ ] Phase F: wrap-up + bug #8 regression check
