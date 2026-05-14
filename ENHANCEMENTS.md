# Enhancement candidates — SMW recomp

Open enhancement opportunities discovered during recompiler / cfg
work, but deferred because the underlying analyzer or framework
piece needed first investment exceeds the value of the immediate
fix.

Format: one section per enhancement. Each captures (a) what was
attempted, (b) why it's blocked, (c) what would unblock it,
(d) anything stashed for revival.

---

## Non-leaf exit-(M, X) auto-routing — blocked by analyzer gap (2026-05-13)

### What was attempted

Extend `snesrecomp/recompiler/v2/exit_mx_autoroute.py` to detect not
just leaf functions whose body's SEP/REP mutates (M, X), but also
**non-leaf functions** whose JSR/JSL targets all have known exits
(cfg-declared OR routed leaves OR earlier-routed non-leaves). The
goal: close the remaining cfg `exit_mx_at` debt class so the two
hand-annotated sites at `$00:F461` / `$00:F465` ("Mario dies on
slope" fix) get auto-detected too, alongside any silent latents.

Two attempts:

**Attempt 1** — pre-variant-discovery, all-4-(M,X)-broadcast
internal known-exits map. Detected 9 routes (5 round-1 + 4 round-2
HandleSPCUploads chain). Regen clean, build clean. **Visual: level
tilemap corruption** — Yoshi's Island intro rendered mostly black,
Mario+blocks in upper-left corner, HUD displaced. Diagnosed root
cause: the detector's internal broadcast filled callee_exit_mx for
phantom entry variants (e.g. `(0, 0)` entries that were never
reached), so the detector consulted phantom values when analyzing
non-leaf candidates and committed exits computed under polluted
assumptions.

**Attempt 2** — post-variant-discovery, per-discovered-variant
gate. Rebuilt callee_exit_mx using the SAME broadcast semantics as
`v2_regen.py`'s emit-time builder (only actually-discovered
variants). Added consistency gate (all variants of F must produce
the same unambiguous exit) and change gate (exit must differ from
at least one entry variant). 10 routes detected (the 9 from
attempt 1 + 1 new at `$00:F44D
GetPlayerLevelCollisionMap16ID_WallRun` with `variants=3`). Build
clean. **Visual: same level tilemap corruption.**

**Attempt 3** — bisected via allowlist env var, restricted to the
6 SPCUploads routes (audio-only, lowest visual-blast surface).
**Still broke** — and broke *differently* (HUD doubled at bottom-
left and bottom-right). That HUD doubling pinned the gap below.

### Why it's blocked: the analyzer can't see PHP/PLP preservation

`v2/decoder.py::analyze_function_exit_mx` walks the decoded graph's
RTS/RTL terminators and reads their `m_flag` / `x_flag`. Each
terminator's flag is whatever the decoder's static propagation
computed at that point — SEP/REP mutate, JSR fall-through key
either preserves (no callee_exit_mx hit) or adopts callee's exit.

The decoder does NOT model `PHP` / `PLP`. A 65816 function that
preserves caller flags via:

```
fn:    PHP            ; push caller P
       SEP #$20       ; set M=1 locally
       ... body ...
       PLP            ; restore caller P
       RTS
```

…is invisible to the analyzer. The decoder sees `SEP #$20 → m=1`
and propagates m=1 onward; the PLP is treated as a no-op for
flag tracking. The RTS terminator's m_flag reads 1. The analyzer
reports exit `(1, …)`. **Reality**: PLP restores caller's P,
including caller's original M flag, so the function preserves M
from caller's perspective.

SMW uses this idiom heavily in audio (`HandleSPCUploads_*`),
DMA-glue, and likely other NMI-adjacent code that needs SEP/REP
locally but must restore caller's environment because callers
sit in tight loops with assumed flag state.

When the auto-router commits a route based on this
mis-analysis, callers' post-call body gets re-decoded with the
WRONG (M, X), producing operand-width mismatches that propagate
opcodes into operand bytes — and at runtime the JSR DID
preserve flags, so the caller's body's intended bytes execute
under DIFFERENT widths than the recompiler emitted. Result:
arbitrary corruption that surfaces wherever those callers
write to SNES state (Map16 tilemap, OAM, palette, etc.).

### What would unblock it

The analyzer needs to recognize the **balanced PHP/PLP wrapper
pattern** and treat the function as preserving the wrapped flags
regardless of internal SEP/REP. Concrete approach:

1. Add a pre-pass over each decoded graph that scans for PHP
   instructions on every entry path and PLP instructions on every
   RTS-reaching path. If every entry path's PHP is matched by a
   PLP on every reaching RTS path (with matching stack depth at
   the wrap points), classify the function as
   `flag_preserving_wrapper`.
2. `analyze_function_exit_mx` returns `(entry_m, entry_x)`
   unconditionally for such functions — the wrapped body's
   internal SEP/REP is invisible to callers.
3. Optional: detect partial wrappers (preserves only M or only X,
   via `PHP / SEP / ... / PLP` plus an explicit `SEP/REP` after
   PLP to set a flag deliberately). Lower priority.

Alternative (richer): full P-flag dataflow with PHP/PLP modeled as
push/pop of a flag-state stack. More work, more general — also
captures PHP/RTI patterns that we don't currently care about.

### What's stashed for revival

snesrecomp working tree, two stash entries (most recent first):

- `non-leaf per-variant exit-(M,X) class fix — blocked by PHP/PLP
  analyzer gap (2026-05-13)` — per-variant gate, post-variant-
  discovery, `EXIT_MX_NON_LEAF_ALLOWLIST` env-var bisection hook.
  This is the version to revive once the analyzer learns PHP/PLP.
- `non-leaf exit-(M,X) class fix — regressed attract demo (level
  tilemap corruption); abandoning per user 2026-05-13` — the
  earlier pre-variant-discovery attempt. Strictly inferior;
  revivable only for reference.

Recover via `git -C snesrecomp stash list` + `stash pop`.

### Why this is an enhancement not a bug

The leaf auto-router landed 2026-05-11 (snesrecomp `14c8eea`) and
is correctly conservative — it skips any function with JSR/JSL in
the body. That covers the 23 leaf-only mutations cleanly and is
the current shipping state. The two hand-annotated non-leaf
`exit_mx_at` directives at `$00:F461` / `$00:F465` continue to
handle the "Mario dies on slope" case. No live bug; just a
remaining class-fix opportunity that needs analyzer investment
before the auto-router can take it on safely.

---

## Leaf auto-router multi-variant gap (2026-05-14)

### What's missing

`snesrecomp/recompiler/v2/exit_mx_autoroute.py::detect_and_route`
scans each cfg `func` entry's DECLARED entry `(m, x)` only. For
functions whose body's effect on (M, X) depends on the entry state
— e.g. `SEP #$20` is a no-op under entry m=1 but mutating under
entry m=0 — the router misses the mutating variants if the
declared entry happens to be the non-mutating one.

`FileSelectColorMath` at `$00:9D30` is the canonical case (closed
2026-05-14 by hand-annotated `exit_mx_at 009d30 1 1` in
`recomp/bank00.cfg`):

- Body: `STA $0701 ; STY $40 ; SEP #$20 ; RTS` (3 insns + SEP + RTS,
  no JSR/JSL — leaf).
- Cfg-declared entry (M1X1): SEP is a no-op, exit = entry, router
  skips.
- Discovered M0X1 entry (called from `GameMode08_FileSelect_M1X1`
  after `REP #$20` at `$00:9CD1`): SEP forces m=1, exit (1,1)
  differs from entry (0,1).
- Visible symptom: file-select crashed at first call with off-rails
  hint `$00:D000FF` inside `CheckWhichControllersArePluggedIn` at
  `$00:9A53`, because the decoder assumed (M, X) preserved across
  the JSR at `$9CD8`, fell through into the wrong variant of
  `HandleMenuCursor_9ACB`, which mis-decoded operand widths.

### Why a class fix is hard

The cfg `exit_mx_at <addr> <m> <x>` directive is per-PC, not
per-entry-variant. For functions whose exit depends on entry:

- `FileSelectColorMath`: forces m=1, preserves x. Across 4 entry
  (m, x) combos, exits are (1,0), (1,1), (1,0), (1,1) — three
  distinct tuples. No single `exit_mx_at` covers all entries.
- For SMW today, only M0X1 + M1X1 are discovered, and both have
  x=1, so `1 1` is correct for all live callers.

A generalized fix needs one of:

1. Per-variant `exit_mx_at` cfg directive (schema change).
2. "Preserve" sentinel (e.g. `exit_mx_at 9d30 1 -` meaning x kept
   from entry).
3. Reorder pipeline so variant discovery runs before the auto-router,
   then commit per-discovered-entry routes.

Each is a multi-day investment. Hand-annotation matches the existing
$00:F461 / $00:F465 pattern and is provably correct against
SMWDisX + the ROM bytes; deferred to whichever (m, x) site shows up
next.

### Detection heuristic for future audit

When the next "variant mismatch → off-rails inside an apparently
correct callee" surfaces, the audit is mechanical:

1. Scan all 4 (m, x) entry combos for every cfg `func` whose body
   has no JSR/JSL.
2. Flag the leafs where some entry's exit (m, x) differs from
   that entry's (m, x) AND that entry was discovered.
3. Hand-annotate `exit_mx_at` per flagged site.

This is bounded (one pass over the cfg, ~5 minutes per regen) but
not autonomous until the per-variant directive lands.
