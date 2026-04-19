# Priorities

North star: **all-native-code execution of stock SMW**. Every hand-written
body in `src/smw_*.c` is a gotcha waiting to happen — divergence from the
ROM, wrong calling convention, silent behavior drift. The recompiler is
the only authoritative translator; every line we can retire to gen is a
line we can't have a bug in.

Work is tracked top-to-bottom. Complete a section before starting the
next. Within a section, commit after each landing so rollback is cheap.

---

## Done

- **Issue A — dispatch_known_addrs in augment pass** (snesrecomp c0074c2).
  `recomp.py` no longer decodes dispatch-handler bodies into the caller's
  insn list during `_augment_cfg_sigs_one_pass`, cutting phantom live-in
  cascade. Shipped with `test_decode_func_terminates_dispatch_when_all_
  handlers_known`.
- **SMW_DISABLE_LM compile-time toggle**. `HAS_LM_FEATURE(i)` and
  `HAS_HACK(i)` collapse to `0` when `SMW_DISABLE_LM` is defined
  (default ON in all four vcxproj configs). MSVC dead-codes the Lunar
  Magic emulation layer out of the binary. Undefining the macro restores
  LM-patched-ROM support.
- **SMWDisX harness v0.1** (`tools/smwdisx_compare.py`). Parses
  `SMW_U.sym` for per-label code/data classification; runs `decode_func`
  on every cfg func; flags instructions whose addresses land inside
  SMWDisX-declared DATA regions. Auto-detects dispatch helpers before
  decoding. Current baseline: 97.4% pass rate, 47 FAILs (decoder walks
  into data — separate triage bucket from skips).
- **Skip elimination — all four tiers complete**. 38 → 1 skip across
  the codebase. The one remaining skip (`Spr036_Unused_DataTable` in
  bank 01) is a legitimate no-op: the ROM's CallSpriteMain dispatch
  table has `dw DATA_01E41F` for sprite $36, which points at real data
  bytes. Empty body matches observed ROM semantics (rule -1 compatible).
  - Tier 1 (bank 0c): 2 → 0 — phantom auto_XX deletions
  - Tier 2 (bank 02): 3 → 0 — struct-return via hand-body-aware sync
  - Tier 3 (bank 01): 6 → 1 — struct-return family (CheckTilting,
    Spr0A7, Spr05F, Spr029_IggyLarry) + carry-return sigs
  - Tier 4 (bank 03): 27 → 0 — clipping/collision, SubOffscreen
    multi-entry, phantom dispatch fakes (Firework table cap), Mode7
    tilemap/sprite anim, Peach/Bowser/KoopaKid/GameMode12, Spr0BD
    carry-merge, Spr0A0 ReturnsTwice (PLA/PLA/RTS auto-detected by
    recompiler — no framework work needed)
- **Framework machinery that landed**: hand-body-aware reconciliation
  in `sync_funcs_h.py` (scans `src/*.c` + cfg verbatim blocks; when no
  hand body exists, funcs.h rebuilds from cfg ret-type + gen params,
  filtering out non-register pointer/struct params so stale sigs get
  dropped). Pinned by 3 tests in `test_sync_funcs_h.py`.

## Active: real SPC via recompiled code (no bifurcation)

North star: SMW audio runs through the real SPC700 emulator executed
*from the recompiled C path*, not through the HLE `g_spc_player`
byebye. The HLE SPC player is a parallel implementation we keep only
because the recompiled path doesn't currently survive the boot
handshake. Getting real SPC working retires `g_spc_player`
permanently — one less hand-written audio simulator to maintain, one
less place where game #2's audio behavior can diverge from its ROM.

Two framework gaps that blocked real SPC are now fixed:

- **M-flag width through SEP #$20** (snesrecomp@7dc2cdc). SEP #$20 now
  narrows `self.A` to `(uint8)` so the $BBAA handshake's 8-bit CMP
  against `$2140` reads the correct byte instead of a 16-bit leftover.
- **Decode-order fall-through repair** (snesrecomp@48a11cd). Non-
  terminator insns whose ROM fall-through lands on decoded-earlier
  code now get an explicit `goto label_<pc+length>` so `v13++;` at
  `$809f` wraps back to `label_80a0` instead of falling off the
  function.

One blocker remains: at runtime, `snes_readBBus` returns `0` for APU
port reads unless `g_is_uploading_apu` is true. That flag is only
flipped by `FixBugHook($80F7)`, which fires under the CPU emulator's
opcode dispatcher — never from recompiled function calls. So the
recompiled `HandleSPCUploads_Inner`'s $BBAA poll reads `0` forever
and the watchdog fires.

### Route A (primary): collapse `g_is_uploading_apu` into `g_use_my_apu_code`

The `g_is_uploading_apu` flag exists to distinguish "HLE mode, APU
not running" from "real mode, APU is running." We already encode
that distinction in `g_use_my_apu_code`. The flag is redundant.

Change:
- `snes_readBBus` APU-port branch: `if (g_use_my_apu_code) return 0;
  snes_catchupApu(snes); return snes->apu->outPorts[adr & 0x3];`
- `RtlApuWrite`: under `!g_use_my_apu_code`, always catch up + write
  to `inPorts` directly. Under HLE, keep the queue machinery.
- Delete `g_is_uploading_apu`, `RtlSetUploadingApu`, and the four
  `FixBugHook($811D/$80F7/$80FB/$817e)` entries in `smw_cpu_infra.c`
  that only existed to toggle it.

Under real SPC, APU I/O then works unconditionally — no anomaly to
mark. The recompiled `HandleSPCUploads_Inner` body runs natively,
talks to the real APU, the handshake completes.

Validation: unstub `HandleSPCUploads_Inner` (cfg + gen_stubs.c), set
`g_use_my_apu_code = false`, regen bank 00, rebuild, run paused,
confirm frame 0 completes without watchdog. Real audio during
gameplay proves the full pipeline.

### Route B (fallback, only if Route A leaves a real anomaly): cfg entry/exit hook directive

If it turns out there's actually state coordination between the
recompiled code and the host runtime that can't be dissolved at the
I/O layer, then we add a genuinely game-agnostic framework feature:
`func NAME ADDR end:X sig:Y enter:CallableA exit:CallableB`. The
recompiler emits `CallableA();` as the first statement of the
function body and `CallableB();` before every `return;`. Game-side
provides the Enter/Exit bodies.

This is a legitimate framework capability — any recompiled game may
have HW-adjacent routines that need runtime bridging — and is a
legal cfg use under rule 0c (encodes per-ROM-address calling
convention that can't be derived from ROM bytes). But Route A
dissolves the specific blocker without needing it, so we only build
this if Route A exposes a case where the I/O layer can't absorb
the coordination.

### Scope guardrails

- Route A touches `snesrecomp/runner/src/snes/snes.c` +
  `snesrecomp/runner/src/common_rtl.c` + `src/smw_cpu_infra.c` only.
  No gen edits, no new cfg directives.
- `g_spc_player` is the parallel-implementation smell we're paying
  off. Do not keep it "for fallback" — the point is to retire it.
- If Route A passes frame-0 but audio sounds wrong mid-game, that's
  a symptom to diagnose via the ring buffer, not a reason to keep
  HLE around.

## Queued: SMWDisX harness v0.2 — mnemonic + operand parity

v0.1 catches "decoder walked into data." v0.2 catches "decoder read a
different instruction than SMWDisX did at the same address." Needed
because v0.1 passes don't prove instruction correctness — they only
prove we're at least in the code region.

Design: parse each `bank_XX.asm` line-by-line to extract
`(addr, mnem, operand)` per instruction. Compare against `decode_func`
output. Handle:
- Macros (`%BorW(LDA, addr)`, `%insert_empty`, `%WorB`, etc.) — expand
  from `SMWDisX/macros.asm` by substitution.
- `if ver_is_XXX(!_VER)` conditional blocks — select U-ROM branch (done
  in v0.1's prototype parser, port properly).
- `con($XX,$XX,$XX,$XX,$XX)` per-version constants — pick [1] for U.
- Anonymous labels (`+`, `-`, `++`, `--`) — re-resolve per basic block.

Growth plan:
- v0.2: mnemonic + operand parity (this phase)
- v0.3: M/X state tracking
- v0.4: full macro + conditional handling
- v0.5: repo-wide pass-rate dashboard in CI

## Queued: warning elimination

Current warning count: ~58. Two work items:

- **Issue B — FuncU8J / FuncU8A / FuncU8JA union-sig dispatch**.
  Dispatch-target guard at `recomp.py:1627` caps `FuncU8*` handlers to
  `void()` or `void(uint8 k)`. Collect dispatch targets, compute union
  live-in across handlers, widen all handlers in each table to the
  union sig, emit matching cast type. Target: the remaining
  `RECOMP_WARN: X/A/j unknown at call site` warnings collapse.
  Typedef family goes in `snesrecomp/runner/src/types.h`.

- **Live-in rescue for mid-body PH/PL scribble-restore pattern**. When
  `…PHX ; TYX ; JSL ; PLX ; <read X>` appears mid-body, entry-X is
  legitimately live-in but current `_insn_reg_use` (recomp.py:499)
  doesn't detect it because it intentionally skips PH/PL as register
  reads. Only pursue if harness v0.2 surfaces false narrowings.

## Harness-flagged FAIL triage — DONE

47 FAILs → 0 FAILs / 100.0% pass rate (2051/2051). Three framework
fixes + one stale-cfg deletion. NO cfg `end:`/`name`/`exclude_range`
additions.

Harness pipeline fixes (commit d6d4a5a):

 1. Harness now calls `discover_bank` + `promote_sub_entries` before
    decoding, matching the real regen pipeline. Without that step the
    harness's `known_func_addrs` was incomplete, so dispatch-entry
    acceptance was looser (non-known entries treated as maybe-real,
    causing the decoder to over-read past table ends in the harness
    but not in the real build).
 2. Code-vs-data check now uses the parser's per-byte `data_addrs`
    set (from db/dw/dl/dd directives) instead of label-region lookup.
    The label-based check false-positived when an anonymous-labeled
    code block (`+`/`-`) sat between a `DATA_XX` label and the next
    `CODE_XX` label — not in SMW_U.sym.
 3. `dispatch_known_addrs` now threaded into decode_func so the Issue
    A terminal-dispatch fix applies to harness decodes too.

Framework fixes (snesrecomp 5a92fec):
 1. **Dispatch-table byte range filter** in `discover.py` — rejects
    seeds that land inside inline dispatch table bytes. When an
    earlier walker mis-sizes an instruction (typically 8-bit vs
    16-bit A-mode immediate width), the resulting byte shift can
    produce a phantom JSR/JSL target whose operand lands inside
    some other function's pointer table. These false-positive
    seeds used to be added to the worklist unfiltered. Now rejected
    at add-time (via lookup against accumulated dispatch ranges)
    and in a post-filter sweep for seeds added before the
    containing table's walk.
 2. **Known-handler cluster break** in `decode_func`'s dispatch
    reader — once at least one known-function entry has been
    accepted, any subsequent unknown entry treats as end-of-table.
    Real SNES dispatches are contiguous runs of pointers to real
    code; transition from known→unknown after a known cluster
    almost always means the reader has fallen off the real table
    into data that happens to parse as a valid $8000+ address.

One cfg cleanup (commit 208cc06):
 - Deleted `func GameMode12_PrepareLevel_03DAE2` — orphan entry
   pointing at DATA_03D9DE bytes, zero callers. Legitimate rule 0c
   deletion (cfg entry predating recompiler fix that made it dead
   weight). NOT a new cfg addition.

### Rule-0 lesson that drove these fixes
During initial triage I reflexively added cfg `end:`/`name:`/
`exclude_range` entries to close FAILs. User pushed back: every one
of those edits would have encoded framework-derivable facts as
per-game data, and would recur in Contra III / Mega Man X / any
future SNES game. The correct fix was architectural — teach
discover/decode_func to detect dispatch-table boundaries properly.
That fix amortizes across every game.

Captured in `CLAUDE.md` rule 0a (the north star is the framework,
not green numbers) and rule 0b (bias toward holistic completeness,
never toward speed). Memory: `feedback_north_star_framework_not_tests.md`,
`feedback_cfg_is_last_resort.md`.

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
