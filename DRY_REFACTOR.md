# Plan: DRY width-correctness layer for snesrecomp v2 codegen

## Status (2026-04-30, end of session)

**Steps 1, 2, 3, 5 SHIPPED.** Step 4 (multi-insn fuzz) IN PROGRESS.

| step | what | landed | commit |
|---|---|---|---|
| 1 | `recompiler/v2/widths.py` chokepoint module | ✅ | snesrecomp `fa09fef` |
| 2 | refactor 11 `_emit_*` sites to call helpers | ✅ | snesrecomp `fa09fef` |
| 3 | `tools/lint_codegen_widths.py` + wired into run_tests | ✅ | snesrecomp `c817650` |
| 4 | multi-insn fuzz (`fuzz/snippets_multi_insn.py`) | ⏳ | (next) |
| 5 | `tests/test_emitter_mask_shape.py` (18 tests) | ✅ | snesrecomp `c817650` |

**Acceptance criteria results:**

| signal | target | actual |
|---|---|---|
| ad-hoc width-derivation sites in codegen.py | 0 | **0** ✅ |
| raw width literals in codegen.py | 0 | **12** (all non-width-bound: P-bit positions, addr arithmetic, MVN/MVP $FFFF sentinel) |
| unit tests | green | **221/221** ✅ |
| Release smoke (GM advance) | unchanged | **GM 00→02→04→...→14 (overworld)**, further than before |
| visible regression | none | **none observed** (user-confirmed visual) |

**Latent bug found-and-fixed mechanically by the refactor:** `_emit_bittest`
used bare `cpu->A` (full 16-bit) for the AND that drives the Z flag,
leaking the B-register byte in m=1 contexts. Caught by routing through
`widths.masked` instead of by another reactive trace.

## Follow-up DRY candidates (separate refactors, not part of M/X width)

These are *other* cross-cutting concerns in `codegen.py` with the same
"per-emitter duplication that lets a future bug land" shape. Each is its
own refactor, scoped in priority order:

### A. `cpu_read*` / `cpu_write*` dispatch — high leverage

Every memory-op emitter does:

    fn_r = "cpu_read8" if op.width == 1 else "cpu_read16"
    fn_w = "cpu_write8" if op.width == 1 else "cpu_write16"

~15 sites. Same width-mask risk class: forget the dispatch and slip
a `cpu_read8` into a 16-bit op.

**Fix:** `widths.read_fn(width)` / `widths.write_fn(width)` helpers in
the existing module. ~30 min of work; same template as M/X width
refactor; covered by the existing lint with one extra pattern.

### B. JSL/JSR bank save+restore boilerplate — largest visual repetition

Every cross-bank call site emits:

    uint8 _saved_pb = cpu->PB;
    cpu_trace_pb_change(cpu, 0, _saved_pb, target_bank, CPU_TR_JSL);
    cpu->PB = target_bank;
    target_fn(cpu);
    cpu_trace_pb_change(cpu, 0, cpu->PB, _saved_pb, CPU_TR_RTL);
    cpu->PB = _saved_pb;

~50+ sites in the emitted gen. Risk class: forget one of the trace
calls or the PB restore.

**Fix:** `emitter_helpers.call_with_pb(target_bank, fn_call_str)` →
returns the 6-line block. Touches the JSL/JSR call sites in
`_emit_call` etc. ~2 hours. Larger code-volume reduction than #A.

### C. Stack push/pop micro-pattern — medium leverage

    cpu->S = (uint16)(cpu->S - 1);
    cpu_write8(cpu, 0x00, cpu->S, val);

…and the inverse for pop. ~15 sites.

**Fix:** `stack.push_byte(val)` / `stack.pop_byte()` / `stack.push_word`
helpers. Modest savings; main value is making the stack-direction bug
class (push vs decrement order — 65816 stack is post-decrement) impossible
to spell wrong.

### D. REP/SEP P-mirror sync envelope — partially DRY'd

`_emit_repflags` and `_emit_sepflags` already use the canonical
"mirrors_to_p / modify P / p_to_mirrors" pattern (fixed in 44c96a7).
PLP path uses a different envelope. Could collapse to one helper.

**Fix:** `widths.modify_p(mask_op_str)` in the existing module. Low
priority — the existing two sites are stable and well-commented.

### E. Trace-event boilerplate — low leverage

`cpu_trace_pb_change` / `cpu_trace_db_change` calls around every
bank mutation. Already named, already self-documenting. Centralizing
saves a few lines but adds an indirection. **Skip unless a bug
surfaces.**

## Recommended ordering after Step 4

1. **A** (read/write fn dispatch) — same template, smallest risk, immediate.
2. **B** (JSL bank save+restore) — biggest LoC reduction, but invasive.
3. **C** (stack helpers) — only if a stack-direction bug surfaces.
4. **D**, **E** — optional cleanup.

---

## Context

Over the last week we have shipped a string of structurally-identical width
bugs in `snesrecomp/recompiler/v2/codegen.py`:

- ASL/LSR/ROL/ROR leaked A.high into 8-bit results (8f9369d)
- ADD/SUB/CMP compared 16-bit lhs against 8-bit rhs (5c00d95)
- WriteReg/IncReg/PullReg/Transfer preserved cpu->X.high in 8-bit mode (b39e99b)
- SEP/REP modified cpu->P without first flushing stale flag mirrors (44c96a7)

Each fix landed at a different emitter, was found via a different probe, and
each one was the *correct* fix for its symptom. The pattern is the bug. The
v2 IR already stamps explicit `width: int` on `Alu`, `Shift`, `IncMem`,
`SetNZ`, `BitTest`, etc. (see `recompiler/v2/ir.py:159-238`); width is
*not* lost between decoder and codegen. What is duplicated — and what every
new emitter has to remember — is the per-op derivation of `op_mask`,
`sign`, the masked-operand C expression, and the N/Z flag-set tail. That
duplication is what lets the next sibling bug land.

Goal: collapse the per-emitter masking pattern into a single typed-expression
helper module, add a lint that bans ad-hoc width literals outside it, and
extend the fuzz harness to exercise the producer/consumer pairs that
single-instruction fuzz cannot cover. After this, a new emitter cannot
forget to mask, and the regression is mechanically detectable in CI.

## Current shape (concrete duplication evidence)

`grep "op_mask\|sign =" recompiler/v2/codegen.py` returns **13 sites**, each
re-deriving the same string from `op.width`:

```python
# _emit_alu (line 261)        op_mask = "0xFF" if op.width == 1 else "0xFFFF"
# _emit_alu (line 271)        sign    = "0x80" if op.width == 1 else "0x8000"
# _emit_alu (line 287)        sign    = "0x80" if op.width == 1 else "0x8000"
# _emit_alu (line 315)        sign    = "0x80" if op.width == 1 else "0x8000"
# _emit_alu (line 322)        sign    = "0x80" if op.width == 1 else "0x8000"
# _emit_shift (line 329, 339) sign + op_mask
# _emit_incmem (line 429)     sign
# _emit_bittest (line 444)    sign
# _emit_setnz  (line 503)     sign + mask
# ...
```

`grep "0xFF\b\|0xFFFF\b\|0x80\b\|0x8000\b" codegen.py` returns **55 raw
literals**. The N/Z flag-set tail is duplicated near-verbatim across
`_emit_alu`, `_emit_shift`, `_emit_incmem`, `_emit_increg`, `_emit_writereg`,
`_emit_pullreg`, `_emit_transfer`. Critically, `_emit_setnz` updates
`cpu->P` to keep packed-P consistent with mirrors; the others
(`_emit_alu`, `_emit_shift`, `_emit_incmem`) only update mirrors and rely on
`cpu_mirrors_to_p` at the next REP/SEP boundary to flush. That's load-bearing
and inconsistent, and it is exactly the kind of asymmetry that produces the
next bug.

## Recommended approach (ordered)

### Step 1 — Introduce `recompiler/v2/widths.py` as the only place width literals live

Create one new module with the typed helpers. This is the chokepoint.

```python
# recompiler/v2/widths.py
def op_mask(width: int) -> str:    # "0xFF" / "0xFFFF"
def sign_bit(width: int) -> str:   # "0x80" / "0x8000"
def carry_bit(width: int) -> str:  # "0x100" / "0x10000"
def ctype(width: int) -> str:      # "uint8" / "uint16"

def masked(expr: str, width: int) -> str:
    """Wrap a raw C expression in `(expr & op_mask)`. Use for any
    operand read that must be width-respecting (any ReadReg result
    feeding ALU/shift/compare)."""

def set_nz(src_expr: str, width: int) -> list[str]:
    """Emit the canonical N/Z mirror + cpu->P update for a width-1 or
    width-2 value. Replaces the duplicated N/Z tail in _emit_alu /
    _emit_shift / _emit_incmem / _emit_increg / _emit_pullreg /
    _emit_transfer. Always updates cpu->P so packed-P stays consistent
    with mirrors — fixes the latent asymmetry where some emitters skip
    the cpu->P update."""

def set_carry_from_bit(src_expr: str, bit_mask: str) -> str:
    """`cpu->_flag_C = ((src & bit_mask) != 0) ? 1 : 0;`"""

def set_carry_from_overflow(temp: str, width: int, polarity: str) -> str:
    """ADC: ({tname} & 0x100/0x10000) ? 1 : 0
       SBC: ({tname} & 0x100/0x10000) ? 0 : 1"""

def set_v_adc(lhs_m: str, rhs_m: str, out_v: str, width: int) -> str:
def set_v_sbc(lhs_m: str, rhs_m: str, out_v: str, width: int) -> str:
```

All four boolean-ish width literals (`0xFF`, `0xFFFF`, `0x80`, `0x8000`,
`0x100`, `0x10000`) live in this module and nowhere else in the recompiler.
The module is ~50 lines of pure-string helpers; no IR, no decoder dependency.

### Step 2 — Refactor every existing `_emit_*` in `codegen.py` to call the helpers

Touch sites (all in `recompiler/v2/codegen.py`):

| function | line | what changes |
|---|---|---|
| `_emit_alu` | 241–325 | replace `op_mask`/`sign`/`mask` literals with `widths.*`; replace N/Z tail with `widths.set_nz(...)`; ADC/SBC C and V via helpers |
| `_emit_shift` | 328–372 | `widths.masked(src, w)`, `widths.set_carry_from_bit`, `widths.set_nz` for ASL/LSR/ROL/ROR — all four collapse to a uniform shape |
| `_emit_increg` | 375–419 | replace inline N/Z + ad-hoc 0xFF / 0x80 with helper calls; A vs X/Y branch on m_flag/x_flag stays runtime (hardware contract) but the per-branch N/Z is via `widths.set_nz` |
| `_emit_incmem` | 422–440 | width literals → helpers; N/Z tail → `widths.set_nz` |
| `_emit_bittest` | 443–455 | `widths.sign_bit(w)`, `widths.op_mask` for the V-bit position too (which also has a width-relative `0x40`/`0x4000` form — add `widths.overflow_bit(w)`) |
| `_emit_setnz` | 501–509 | becomes a one-liner `return widths.set_nz(_v(op.src), op.width)` |
| `_emit_pullreg` | 626–707 | per-register width literals → helpers; N/Z → `widths.set_nz` |
| `_emit_transfer` | 710–764 | same |
| `_emit_writereg` | 205–234 | A: m_flag-conditioned high-byte preserve; X/Y: x_flag-conditioned zero-extend. These are **runtime** width branches, so they stay as `if (cpu->m_flag) {...}` C; but the literal masks (`0xFF`, `0xFF00`) come from `widths.*` |

Acceptance criterion for Step 2: `grep -nE "0x(FF|FFFF|80|8000|100|10000)\b" recompiler/v2/codegen.py` returns **zero matches**. All width literals route through `widths.py`.

### Step 3 — Static lint to prevent regression: `tools/lint_codegen_widths.py`

A 30-line Python script that opens `recompiler/v2/codegen.py` and other
`recompiler/v2/*.py` (excluding `widths.py`) and fails if it finds:

- raw `0xFF`, `0xFFFF`, `0x80`, `0x8000`, `0x100`, `0x10000` literals
- the pattern `"0xFF" if .* else "0xFFFF"` or `"0x80" if .* else "0x8000"`
- direct C-string emission like `"& 0xFF"` or `"& 0xFFFF"`

Wire it into `snesrecomp/run_tests.py` so it runs alongside the existing
unit tests. Optional: add a thin shim in `.github/workflows/release.yml` or
a pre-commit hook — but the run_tests.py wiring alone is the load-bearing
gate (matches existing project convention; no new CI infra needed).

A second pass of the lint should ban bare `cpu->A` / `cpu->X` / `cpu->Y`
references in any string literal inside `recompiler/v2/*.py` outside the
register-helper emitters (`_emit_readreg`, `_emit_writereg`, `_emit_increg`,
`_emit_pullreg`, `_emit_pushreg`, `_emit_transfer`). The point is: if a
future emitter wants register state, it must take a `Value` from a
`ReadReg` IR op — never bare-emit a struct field read.

### Step 4 — Fuzz harness: extend `snesrecomp/fuzz/generate_snippets.py` to multi-instruction snippets

Memory: "Phase B fuzz only covers single-instruction state-tracking … carry_chain, flag_src, overflow uncovered." This is the gap the producer/consumer bug class hides in. Single-insn fuzz cannot catch ASL→ROR carry-chain bugs because the carry it tests was set by a constant prologue.

Extend the snippet generator with **producer/consumer pairs**. Concrete pairs to seed (each becomes a category alongside the existing 39 mnemonics):

- ALU-then-ALU carry chain: ADC→ADC, SBC→SBC, ADC→SBC at every M and seed
- Shift carry chain: ASL→ROL, LSR→ROR, ASL→ASL→ROL (3-step)
- Compare-then-branch flag use: CMP→BCC, CMP→BCS, CMP→BEQ, CMP→BNE; same for CPX, CPY
- BIT-then-branch: BIT→BNE, BIT→BMI, BIT→BVS
- Mode boundary: SEP #$20 → ALU op → REP #$20 → ALU op (carries the regression class from 44c96a7)
- INC/DEC-mem-then-branch: INC abs → BNE; tests that `_emit_incmem` Z is right
- Transfer-then-flag: TXA → BMI, TAX → BNE (catches TXA in m=1 / x=0 width slip)

Target: ~500–1000 multi-insn snippets across the categories above. The existing oracle command `fuzz_run_snippet` accepts arbitrary ROM bytes — no oracle-side change needed. The diff/sqlite pipeline (`run_oracle.py` / `run_recomp.py` / `diff.py`) already records per-snippet matched/error rows; just add a `category` column when generating so before/after can group by category.

### Step 5 — One unit test per emitter that asserts the masked-emit shape

Existing tests like `test_accumulator_shift_width.py` verify width *inference*; add tests that verify the *masked-emit shape* — i.e., that the emitted C string contains the helper-generated mask substrings. Once Step 2 is done, this is mechanical:

```python
def test_emit_alu_masks_operands_in_8bit():
    out = _emit_alu(Alu(op=AluOp.CMP, lhs=Vid(1), rhs=Vid(2), width=1, out=None))
    assert "& 0xFF" in "\n".join(out)            # mask present
    assert "& 0xFFFF" not in "\n".join(out)      # no 16-bit slip
```

One test per `_emit_*` touched in Step 2. Run via `run_tests.py`.

## Files to create / modify

**Create:**
- `snesrecomp/recompiler/v2/widths.py` — the helper module (~50 lines)
- `tools/lint_codegen_widths.py` — the lint (~30 lines)
- `snesrecomp/tests/test_emitter_mask_shape.py` — per-emitter unit tests (~100 lines)
- `snesrecomp/fuzz/snippets_multi_insn.py` — multi-insn snippet generator (~200 lines, parallel structure to `generate_snippets.py`)

**Modify:**
- `snesrecomp/recompiler/v2/codegen.py` — refactor 13 width-literal sites to helper calls (Step 2 table above). Net line change should be roughly neutral.
- `snesrecomp/run_tests.py` — invoke the new lint script before running test loop
- `snesrecomp/fuzz/diff.py` — add `category` column to results table; `--by-category` summary mode

**Do not touch:**
- `snesrecomp/recompiler/v2/ir.py` — IR is already correct; width is on every node
- `snesrecomp/recompiler/v2/lowering.py` — width derivation from `insn.m_flag`/`x_flag` is correct
- `snesrecomp/recompiler/v2/decoder.py` — out of scope
- `recomp.py` (v1) — superseded; do not retrofit
- `runner/src/cpu_state.h` — CPU register storage shape is fine; the fix is at emission time, not at storage time
- `src/gen/*.c` — these are regenerated output; they will change when codegen.py is refactored, which is expected. Verify via `test_regen_idempotent.py`.

## Before / after measurement

The next session should capture **all six** numbers below before any code change, then re-capture after Steps 1–3 land, and again after Steps 4–5.

| signal | command | baseline (before) | target (after) |
|---|---|---|---|
| ad-hoc width-literal sites in codegen.py | `grep -cE "op_mask = .0xFF\|sign = .0x80" snesrecomp/recompiler/v2/codegen.py` | **13** | **0** |
| raw width literals in codegen.py | `grep -cE "0x(FF\|FFFF\|80\|8000\|100\|10000)\\b" snesrecomp/recompiler/v2/codegen.py` | **55** | **0** |
| raw width literals in widths.py | (after Step 1) | n/a | 8–12 (one definition each) |
| fuzz pass-rate (single-insn) | `python snesrecomp/fuzz/run_recomp.py && python snesrecomp/fuzz/run_oracle.py && python snesrecomp/fuzz/diff.py` then `SELECT COUNT(*) FROM runs WHERE matched=1` | **1801 / 1801** | unchanged (no regression) |
| fuzz pass-rate (multi-insn) | (after Step 4) `--category-summary` | 0 / 0 (does not exist) | **N/N** for some N ≥ 500 |
| boot smoke + GameMode advance | `tools/boot_smoke.py` (existing) | GM advances 00→02→04→07 at 32fps | unchanged |
| regen idempotency | `python snesrecomp/tests/test_regen_idempotent.py` | green | green |

The two-line decisive signal: **"55 raw width literals → 0"** plus **"multi-insn fuzz: 0 → N green"** is the before/after the user can hand to a code review without further explanation.

## Out of scope (explicit)

- Do not change the IR. Width on IR nodes is correct as designed.
- Do not collapse `_emit_writereg` / `_emit_pullreg` / `_emit_transfer` to compile-time width branches — the runtime `if (cpu->m_flag)` branches are correct because those ops can run before the width has been finalised at decode time (e.g., via PLP). The literals in those branches still route through `widths.*`.
- Do not retrofit v1 `recomp.py`. Memory: "v1 superseded but retained" — not a target.
- Do not pre-emptively rewrite `_emit_bitsetmem` / `_emit_bitclearmem` to use a typed `cpu->A` reader. They use `cpu->A` directly, which is technically a bare-register read; flag for follow-up after the lint lands and surfaces them, but do not bundle the fix here. Memory says these exist; the lint will catch them and the next session can decide whether to fix or whitelist.
- Do not extend fuzz beyond the ~7 producer/consumer categories listed in Step 4. Extending to memory-mode coverage (DP_X, ABS_LONG, etc.) is a separate scope.

## Verification

End-to-end on the next session:

1. `widths.py` lands; `grep` of mask literals in codegen.py drops to 0; `grep` in widths.py shows the canonical definitions.
2. `python snesrecomp/run_tests.py` is green (existing tests + the new per-emitter shape tests + the new lint).
3. Regen all banks: `python snesrecomp/regen_all.py` (or the project-equivalent invocation). `git diff src/gen/` should show structurally trivial changes (whitespace, helper-emitted mask substrings) but byte-identical CPU semantics — sanity-check by spot-reading 3–5 banks.
4. `test_regen_idempotent.py` green (recompiler is deterministic).
5. Boot smoke: launch `smw.exe`, confirm attract demo reaches title screen at 32fps with palette intact (this is the visible regression signal for the recent shift/ALU fixes).
6. Fuzz: `run_recomp.py + run_oracle.py + diff.py` — single-insn pass-rate unchanged at 1801/1801.
7. Multi-insn fuzz: new generator emits ≥500 snippets; `diff.py --by-category` shows green or near-green per category. Any mismatches in multi-insn fuzz are *new bugs the layer just surfaced* — surface them, don't suppress them.
8. Save a one-line Markdown table of the six before/after numbers for the user. That is the deliverable.
