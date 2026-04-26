# Open issues — SMW recomp

## Working policy (read first)

We do not fix individual visible bugs in isolation. Each visible
symptom is a probe into a recompiler / framework gap. The goal is
to identify the **underlying class of recompiler bug** that
generated the symptom, fix that class in the framework
(`snesrecomp/`), regen all banks, and re-evaluate every symptom
together. Per-game cfg shimming is last-resort (Rule 0).

If individual symptom diagnosis is necessary to extract the
underlying pattern, do that work — but the deliverable is always a
framework fix, never a per-symptom patch.

Methodology: golden-oracle (`docs/GOLDEN_TESTING.md`) — diff
recomp vs embedded snes9x at the same state-sync point, narrow to
seed byte → write trace → call trace → block trace → instruction
trace → framework fix.

---

## Session 2026-04-25/26 — post-koopa-shell-pop attract-demo audit

Branch: `post-koopa-discovery` (both repos). Landed:
- `dispatch-extent-multipass` merged to main (snesrecomp): WIP
  reorder + cross-bank thunk-sig-from-funcs.h fix. Koopa-shell-pop
  closed (user visual-confirmed).

After the koopa fix the attract demo runs further than ever, and
the following new visible issues surface. **Looking for the
underlying recompiler-framework cause(s), not per-issue fixes.**

### Issue A — koopa fails to render on 2nd attract-demo cycle

The first cycle of the attract demo renders the koopa correctly.
On the **second** cycle, the koopa is invisible until Mario stomps
it; the moment of contact, the koopa + shell render and eject
normally. After that the koopa is normal for the rest of the cycle.

**Suspected class:** state-carryover across attract-demo loop. A
sprite slot's render state (OAM tile, palette, draw-enable bit)
isn't being re-initialized when the demo restarts. Possible
underlying causes: a NMI/init pathway whose first-time-only branch
isn't taken on the second run, OR a recompiler-side stale-variable
issue where a function's second invocation reuses a stale local
that should have been reset to a WRAM value.

### Issue B — Mario falls below ground level near a ?-block

When Mario walks toward a specific ?-block, he sinks slightly
below the ground tile (single-pixel-or-two drop, then he's stuck
at the lower Y). Should remain at ground level.

**Suspected class:** collision/ground-detection Y-axis arithmetic.
Likely related to Issue C below — both touch ?-block interactions
on the Y axis.

### Issue C — Yoshi floats into the sky after emerging from a ?-block

When the ?-block spawns Yoshi, Yoshi rises and keeps rising (no
gravity applied, or wrong Y velocity sign). Yoshi should drop and
land normally.

**Suspected class:** Y-velocity initialization or gravity-apply
pathway on sprite-spawn-from-block. Strongly likely same root
cause as Issue B (both: Y-axis state at ?-block interaction
boundary).

### Issue D — random dirt tiles in background-layer slopes

Hilly slopes in the BG layer (Layer 2) show random dirt blocks
scattered across the green slope, breaking up the slope graphic.
ROM has clean slope tiles; recomp injects extra dirt tiles.

**Suspected class:** tilemap upload / Layer-2 BG-tilemap source
selection. Possible underlying causes: a tile-source pointer
loaded with wrong width (M=8 vs M=16) reading from the wrong
half-byte; or a dispatch-table over-read (Tier-1 test still red on
29 sites) routing a Layer-2 tile-fetch to the wrong handler.

### Issue E — berries now positioned correctly (positive)

Berries previously rendered too far up-left on the bushes. They
now snap to the correct positions. **No new fix targeted this** —
it was an inadvertent side-effect of the dispatch-extent / thunk-
sig fix landing on main. Worth tracking because it confirms the
class of bug we just fixed reaches farther than the koopa-shell
case.

### Cross-issue pattern hunting (the actual work)

**UPDATE 2026-04-26:** Issue C investigation traced the visible
"Yoshi-floats-up" bug to the chain:

  1. Dispatch over-decode at $01:FAC3 produces phantom entries.
  2. discover_bank promotes one of them ($01:ECEC) as auto_01_ECEC.
  3. The promotion CAPS Spr035_Yoshi's emit range at $ECEC.
  4. Spr035_Yoshi's body decode reaches PC=$ECED (after a JSR);
     end_addr=$ECEC, so the emit closes with a fall-through call
     to auto_01_ECEC.
  5. auto_01_ECEC runs the on-ground init block `LDA #$F0; STA
     SpriteYSpeed,X` every frame, defeating gravity.

**Fix attempts on 2026-04-26 all regressed visible behavior:**
  * Reject auto-promote inside MANUAL func body — broke koopa
    shell-pop (real handlers like SprStatus06 get rejected too).
  * Reject only when dispatch_only AND inside-MANUAL-reach —
    broke YoshiEgg→Yoshi spawn (BigBoo dispatch handlers at
    $F8F8 are dispatch-only AND inside-reach).
  * Suppress the fall-through emit when next_func is dispatch-
    only — broke Yoshi-egg spawn entirely (the egg sprite
    handler vanished).

**All three reverted to baseline state.** The dispatch-overread
class is genuinely subtle: phantom promotions and real body-
internal sub-handlers are not distinguishable by any single
heuristic tried so far. **Future attempts MUST run the
attract-demo regression test** (`test_attract_demo_regression`)
which encodes the visible-behavior invariants we know are
correct. Whack-a-mole regression debt is the cost of NOT
running that test between attempts.

Status as of commit:
  - Issue A (koopa invisible on 2nd attract cycle): OPEN
  - Issue B (Mario falls below ground at ?-block): OPEN
  - Issue C (Yoshi floats up after ?-block hatch): OPEN
  - Issue D (BG slope dirt blocks): OPEN
  - Koopa-stomp shell-pop: WORKING (regression-tested via
    test_attract_demo_regression invariants)
  - Yoshi-egg → Yoshi spawn: WORKING (regression-tested)
  - Demo-progresses-past-boot: WORKING (regression-tested)

Do NOT add per-game cfg entries (exclude_range, jsl_dispatch counts)
to mask any of A–D unless framework fixes are blocked.

---

# Historical: Open issues + session summary from autonomous rip session 2026-04-19/20

## Session summary

Branch: `chore/tier3c-irq-vector` (both repos).

**Framework fixes (snesrecomp/recompiler/recomp.py + tests):**
- STA [dp] / STA [dp],Y in M=0 no longer drops the high byte. New
  `IndirWriteWord` runtime inline. `_emit_sta16` also now handles
  INDIR_Y / INDIR_DPX / DP_INDIR (were falling through to silent
  comment). 6 pinning tests.
- Fall-through-into-excluded-range is no longer emitted as a spurious
  tail call. 2 pinning tests.
- `_emit_function` now emits `RecompStackPop + return` on non-terminal
  bodies with no valid fall-through target so pushed stack frames
  stay balanced.

**Tooling:**
- `tools/sync_funcs_h.py`: orphan-decl deletion, duplicate dedup,
  also scans `snesrecomp/runner/src/*.c` for framework hand bodies,
  prints a scaffolding-smell metric.

**Rips landed on chore/tier3c-irq-vector:**
- Tier 1c: `g_did_finish_level_hook` dead decl.
- Tier 1d (partial): removed 4 `dp_sync` cfg directives from bank0d.cfg;
  bank 0d gen lost 41 stub-call sites. See residual below.
- Tier 3a: `PatchBugs_SMW1` (all 3 hooks were dead given Tier 3c status).
  Null-guarded `PatchBugs()` in the runner.
- Tier 3c/Reset: hand-written `SmwVectorReset` replaced by direct call
  to recompiled `I_RESET` at ROM $00:8000-$806A.
- Tier 3g: rip debug harness, unused vtable slots, HLE SPC executor
  body (~1000 LOC, 33 orphan statics), DspRegWriteHistory field.
  smw_spc_player.c: 1539 -> 71 LOC.
- Dead: `LoadStripeImage_UploadToVRAM` (stripe HLE, 0 callers),
  `UploadOAMBuffer` (superseded-codegen, 0 callers), 8 sprite
  coordinate accessors, `ParseBoolBit`.

**Metrics:**
- Scaffolding smell (hand-bodies in src/*.c): 147 -> 96.
- Release|x64 build: 0 errors, 105 warnings baseline maintained.
- Boot: reaches frame 200+ unchanged; user-confirmed visually
  "equally broken" at session start (ground-rendering bug is
  unchanged because it's a separate codegen issue tracked in
  memory/project_ground_not_rendering_*).
- Parent repo: 16 commits on `chore/tier3c-irq-vector` since main.
  Includes one revert: the globals `ptr_layer1_data / ptr_layer2_data
  / ptr_layer2_is_bg` looked orphan by grep but are live via an
  `extern` decl embedded inside `debug_server.c` — heuristic audit
  tools missed that. No net change for those three; everything else
  stuck.
- snesrecomp subrepo: 4 commits on the same branch — recomp.py
  emitter fixes, PatchBugs null-guard, dead-fn rips in common_rtl
  + common_cpu_infra + debug_server, + SyncDmaChannelToPpuFromSnapshot
  (Tier 1b orphan that had survived the compare-harness rip).
- Release|x64 file: smw_spc_player.c 1539 -> 71 LOC; various other
  src/*.c files shrunk; common_rtl.c lost ~50 lines; debug_server.c
  and common_cpu_infra.c each lost one dead function.

## Open issues after session

## Framework gap: `uint8 k` signature sticks even when callee doesn't read X

Discovered 2026-04-20 while investigating ground-bug's 5× VRAM-write
undercount (frame 95, BG1 tilemap $V2800-$V2FFF: 179 recomp / 909 oracle).

**Symptom.** `src/gen/smw_05_gen.c:212-213` emits:
```c
BufferScrollingTiles_Layer1_Init(0 /* RECOMP_WARN: X unknown at call site */);
BufferScrollingTiles_Layer2_Init(0 /* RECOMP_WARN: X unknown at call site */);
```
inside the 32-iter loop in `InitializeLevelLayer1And2Tilemaps`
($05:809E). The call sits after a loop back-edge; `_build_call_args`'s
in-BB X tracker (`self.X`) is None, so it emits `0` with WARN.

**Why the sig says `uint8 k` at all.** All 6 dispatched Buffer*
functions (Layer1, Layer1_NoScroll, Layer1_VerticalLevel, Layer2,
Layer2_Background, Layer2_VerticalLevel) carry `(uint8 k)` in
`recomp/funcs.h`, yet grep shows **exactly 1 `\bk\b` match per
function body** — the declaration line. `k` is never read. The sig
is wrong.

**Root.** `_augment_sig_with_livein` in `recomp.py:989-1039` is
deliberately one-way: "This pass only WIDENS: it never drops a param
that's already in the sig, even when live-in says the register isn't
consumed." Rationale in the docstring: live-in analysis is
conservative, has known gaps (PHX…PLX scribble-restore, DP-indirect
reads), and hand-written callers codify the true ABI. Dropping a sig
param could break them.

Consequence: once `(uint8 k)` got introduced at any point in history
(probably via a tail-call propagating `reads X` upward in
`infer_live_in_regs` at lines 709-715), the sig is pinned forever,
and every caller that can't resolve X at the call site emits a
WARN + wrong-looking `0` argument.

**Why this case is harmless.** In these 6 callees, `k` is dead, so
passing 0 is semantically equivalent to passing the real X. The WARN
is cosmetic clutter. But the framework invariant is fragile: the next
time a dispatch target DOES read X, the same caller-side pattern
would silently miscompile.

**What a fix looks like (scoped, not done in this session):**

1. **Sig narrowing** (most direct): teach the widening pass to also
   narrow when liveness *definitively* says the register isn't live-in
   AND the body contains no PHX…PLX scribble-restore pattern AND no
   DP-indirect read of `$7E:XX` where X is used as index. Guarded
   behind a cfg opt-in for rollout safety. Requires regen of every
   bank + regression eyeball.
2. **Unused-param elimination at emit time**: during function emit,
   scan generated body for `\bk\b`; if absent, rewrite sig to drop
   `uint8 k` post-emit and propagate to the sync_funcs_h writer.
   Then any caller re-resolves against the narrower sig. Smaller
   blast radius than Option 1.
3. **Cross-BB X tracking in the caller tracker**: carry `self.X`
   through loop back-edges via join/fixpoint. Even with this, a
   TAX-from-runtime-value pattern (as here) would still give "X
   unknown at call site" → falls back to Option 2 anyway.

All three are non-trivial. Design review recommended before
implementation.

**Until then:** `RECOMP_WARN: X unknown at call site` in generated
output is acceptable only when an independent check confirms the
callee doesn't read `k`. Do not claim the WARN is the root cause of
a runtime divergence without that check (ground-bug 2026-04-20:
confirmed dead, NOT the cause).



## Tier 1d dp_sync residual — dispatch file still calls no-op stubs

After bank 0d regen'd with the `dp_sync` cfg directives deleted, bank
0d's generated `dp_sync_map16_ptr()` / `dp_sync_map16_ptr_bak()`
calls are gone (41 → 0). But `src/gen/smw_0d_dispatch.c` still makes
10 hand-written calls to `dp_sync_map16_ptr_to_dp()` — see lines 48,
59, 64, 78, 87, 100, 113 (and a couple more).

`smw_0d_dispatch.c` claims in its header comment to be "Extracted
from tools/recomp/bank0d.cfg verbatim block" but there is NO
verbatim_start/verbatim_end block in bank0d.cfg. The file is in
practice hand-maintained despite living in `src/gen/`. Rule 7 says
don't hand-edit gen files; this is a real rule-7 conflict since the
file has no generator.

**What I deferred:** deleting the three dp_sync stub no-op bodies
from `src/dp_sync_bridge.c` and removing the file. Can't delete them
while the dispatch file still calls `dp_sync_map16_ptr_to_dp()` — the
build would break. The stubs remain as no-ops; runtime cost is zero.

**Options for next session:**
1. Rewrite `smw_0d_dispatch.c` by hand to drop the `dp_sync_map16_ptr_to_dp()`
   calls (acknowledge rule-7 exception: the file has no generator, it IS
   hand-written). Then delete the stubs + file + funcs.h decls.
2. Build an actual dispatch generator (tools/gen_dispatch.py or similar)
   and regenerate without the dp_sync calls. Heavier lift but removes the
   rule-7 conflict permanently.

Committed as part of the dp_sync cfg removal. Smell count: 146 unchanged
(stubs still in src/dp_sync_bridge.c).

## Tier 3b kPatchedCarrys_SMW — CLOSED 2026-04-20

Resolved by verifying the 46 patch addresses were already dead for
runtime. Cross-check: `tools/check_patch_carrys.py` confirmed every
entry lives in a recompiled bank (00-04) and outside every
`exclude_range` in those cfgs. Recompiled paths thread C explicitly
in generated code, so the interpreter never saw these sites — the
BRK patches were masking nothing.

Ripped: the 46-entry array, `patch_carrys`/`patch_carrys_count` on
`RtlGameInfo`, `kPatchedCarrysOrg[]` buffer, `FixupCarry()`, the
init-time ROM-byte patcher, the `CpuOpcodeHook` carry loop, and the
ADC/SBC carry-set switch cases in `cpu.c`'s BRK handler. Framework
no longer needs a reaching-defs carry inference pass for this — the
premise (interpreter executing ADC/SBC with unset carry) was stale.

## Tier 3g residual — HLE SPC executor body (~900 lines)

After this session's partial Tier 3g work (rip debug harness + rip
unused vtable slots), the HLE SPC engine body in `src/smw_spc_player.c`
is now entirely unreachable: its only public entry point was the
`gen_samples` vtable slot, which was never called and has been deleted.

Unreachable pieces:
- Spc_Loop_Part2, Sfx0_Process, Sfx3_Process, PlayNote, ComputePeriod,
  WritePitch, Dsp_Write, Sfx0_TurnOffChannel, Sfx3_TurnOffChannel,
  SetEchoVolume, SetEchoOff, Port1_WriteInstrument, Chan_DoAnyFade,
  CalcFinalVolume, and many statics. ~900 LOC.

**Why deferred:** individual hand-body removals work in batches of
5-10 functions max if there's a risk of link-time or compile-time
fallout (e.g. one function calls another, removing wrong one first
breaks link). A full HLE-executor rip needs a dependency audit first
so functions are removed in leaf-first order. Overnight-autonomous
is a poor fit.

**Next session approach:**
1. Build a call graph of just smw_spc_player.c statics.
2. Topologically remove from leaves up, rebuilding after each batch.
3. Keep Spc_Reset + SmwSpcPlayer_CopyVariablesFromRam (live).
4. Keep SmwSpcPlayer_Upload + everything it transitively calls (live).
5. Delete everything else.

Estimated residual after that rip: smw_spc_player.c shrinks from
~1300 lines to ~150 lines.
