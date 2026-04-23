# Bug #8 Investigation — Tooling Retrospective

## Status

**Bug #8 root cause narrowed to a single flow-path divergence in
`RunPlayerBlockCode_EB77` at mode-0x04 entry.** Recomp takes a
different branch from oracle through the ~850-line gen'd C body of
this function, causing the $72 (PlayerInAir) clearing chain to not
fire during level-load. By the time `$EE3A` is reached on recomp
(frame 210, mid-mode-0x07), Mario has already fallen one tile deeper
than oracle. Full fix deferred to next session.

## What this document is

A post-mortem of the tooling we built and used to root-cause Bug #8,
and a concrete statement of what we couldn't have found without it.
The investigation itself was ~6 hours of focused probing; the "first
divergence" was pinned to a specific byte ($72 PlayerInAir) within
the first hour, because every tool below was already in the tree and
usable without rebuild.

## The bug in one sentence

Mario's Y position at attract-demo landing is 16 pixels (one 16x16
map-tile) lower on recomp than oracle. Mario visually sinks into the
ground block.

## Tool stack, in order of how we used them

### 1. State-synced divergence scanner (new this session)

`_probe_bug8_state_synced_divergence.py`

Both sides hit `GameMode=0x07` at different frame numbers (recomp at
f201, oracle at f405 — 204-frame boot-timing delta). Frame-number
diffs are meaningless during boot. The scanner steps recomp until
**recomp's** GameMode=0x07, then steps oracle alone (via `emu_step`)
until **oracle's** GameMode=0x07 — both sides at dwell=0 in mode 0x07
on their own independent timelines. At that moment, and again at
dwell=1..5, it diffs `$0070-$009F` (player-scratch zone).

**Finding:** at mode-0x07 entry (dwell=0), `$72 PlayerInAir` is already
`0x24` on recomp and `0x00` on oracle. Every subsequent dwell shows
`$7D (PlayerYSpeed_hi)` accumulating on recomp (0x06 → 0x0c → 0x12 →
0x18 → 0x1e) while staying 0x06 on oracle. That's the gravity cascade
caused by recomp's wrong-in-air flag.

**Why it matters:** frame-number-based tests (like the v2 golden
fixture) would show a wall of ~15 differing bytes at dwell=30 without
pointing at the root. State-synced dwell-0 diffing zeroes in on the
seed of divergence immediately.

**Why this wasn't doable before:** `emu_step` (oracle-only step) and
`emu_read_wram` had to be wired into the Oracle build. We had them;
the insight was using them for independent mode-sync rather than
lockstep stepping.

### 2. Tier-1 $72 writer trace (both sides)

`_probe_bug8_72_writer_compare.py`

Two commands armed in parallel:
- Recomp: `trace_wram 72 72` — records every `RDB_STORE8(0x72, ...)`
  with `old`, `new`, `func` (`g_last_recomp_func`), and `parent`
  (stack one level up).
- Oracle: `emu_wram_trace_add 0x72 0x72` — snes9x's bus-write hook
  installed via `s9x_write_hook_trampoline`, recording `before`,
  `after`, and the 24-bit PC of the writing instruction.

**Finding:**
- Recomp writes `$72` four times: once at f0 (init, 0→0), twice at
  f94 (level-load init, 0→0 and 0→0x24 from `InitializeLevelRAM_00A6CC`).
  No writes after f94.
- Oracle writes `$72` five times: init, re-init, `InitializeLevelRAM`
  (same as recomp), then crucially at oracle-f296 `PC=$00EF6D`
  `0x24→0x00`.

**Why it matters:** This pinned the exact instruction (`STZ.B
PlayerInAir` at ROM `$EF6B`, PC logged post-increment at `$EF6D`) that
clears `$72` on oracle. Without the oracle-side PC trace we'd know
"$72 is wrong" but not "which instruction should have cleared it."

**Why this wasn't doable before:** Oracle needs an embedded emulator
that exposes bus-write hooks. We now have that via snes9x's
`s9x_write_hook`. SMW recompiler projects historically used
hand-written HLE as the "oracle" — those can't answer "which ROM
instruction wrote this byte" because they don't execute ROM code.

### 3. Tier-1.5 call trace with contains/from/to filters

`trace_calls` + `get_call_trace contains=<name> from=<f> to=<f>`

Arms a 65536-entry ring buffer on every `RecompStackPush`. Retrieval
accepts filters so you don't have to page through millions of entries.

**Finding (initial, misleading):** `contains=RunPlayerBlockCode_00EEE1`
returned 0 hits across all frames → "the clear function never runs."

**Finding (corrected, after buffer-truncation fix):** When searched
per-window via `from=N to=N+35`, the 0-hit conclusion for
`GameMode04_PrepareTitleScreen` and `RunPlayerBlockCode_EB77` was
**wrong** — those DO fire at f95; the initial broad dump had truncated
output buffer and emitted only frames 0-64.

**Why it matters:** We nearly spent hours chasing a wrong hypothesis
(that mode 0x04's handler never runs on recomp) because the first
trace query appeared conclusive. Restructuring the query to window
per-frame revealed the real story: mode 0x04 DOES run, the
`RunPlayerBlockCode_EB77` path IS entered at f95, but the flow INSIDE
EB77 diverges.

**Lesson baked into investigation protocol (CLAUDE.md):** treat any
0-hit result from a bounded-output ring query as "inconclusive until
you've exhausted the ring with paginated queries."

### 4. Tier-2.5 watchpoint + full recomp stack snapshot (new this session)

`watch_add 100 04` + `parked` (extended this session)

Pauses recomp synchronously when $0100 is written with value 0x04
(the premature mode-0x03 → 0x04 transition). Returns not just the
writer function name but now the **full recomp call stack** at the
moment of the write, up to 16 frames deep.

**Implementation:** Extended `rdb_check_watch` in `debug_server.c` to
snapshot `g_recomp_stack[]` into `s_rdb_parked_stack[16][48]` at hit
time, before parking the main thread. `cmd_parked` emits it as a JSON
`stack` array.

**Finding:** At the $0100=4 write, `stack_depth=39` with **eleven
repeated `auto_0D_A40F`** entries and **nine `auto_05_86EA`** entries
piled up. The stack leaked — ProcessStandardAndTilesetSpecificObjects
at ROM `$0DA415` is a `JSL ExecutePtrLong` tail-call dispatcher that
the generator emits with a `RecompStackPush` but no matching Pop.

**Why it matters:** This single diagnostic revealed that
`g_last_recomp_func` attribution is **unreliable** under tail-call
dispatch patterns. The writer shown in trace_wram's `func` field
("LoadSublevel_02A751") was a stale entry — the actual writer (line
5859 in smw_00_gen.c at ROM $009749 inside `GameMode11_LoadSublevel_0096D5`)
never updated the global because the previous callee leaked. Without
the stack snapshot we'd have kept chasing `LoadSublevel_02A751` as the
culprit.

**Why this wasn't doable before:** `parked` only reported
`g_last_recomp_func` (a single name). We had the ring, the push/pop
infrastructure, but no probe to surface the full stack at a specific
moment.

### 5. GameMode transition timeline (new this session)

`_probe_bug8_gamemode_timeline.py`

Steps both sides and logs `$0100` (GameMode) on each. Built a simple
table showing which recomp-frame and oracle-frame each side enters
each mode. Revealed:

- Recomp mode 0x03 = 1 frame. Oracle mode 0x03 = 20 frames.
- Recomp mode 0x06 = 1 frame. Oracle mode 0x06 = 75 frames.
- Oracle runs in emulated cycle-accurate time; recomp runs the C body
  of each mode to completion in one main-loop iteration.

**Important false-lead avoided:** This looked like "recomp is skipping
modes." It's not — the ROM genuinely does all the level-load work in
one long no-NMI stretch on hardware too. The 20-frame oracle dwell is
just the emulated CPU-cycle consumption, not real frame yields. The
same ROM code runs on both sides in the same sequence. **This was key
to avoiding a wrong-direction fix.**

### 6. Oracle per-instruction PC trace (existed, first used at scale this session)

`emu_insn_trace_on` + `emu_get_insn_trace pc_lo=... pc_hi=... limit=...`

Records full hardware register state on every CPU instruction dispatch
inside snes9x — `frame, pc24, op, A, X, Y, S, D, DB, P_W, cycles`.
1M-entry ring; covers ~33 frames of execution.

**Use:** armed around oracle-f296, then filtered to `pc_lo=0xee00
pc_hi=0xefff`. Output revealed the exact 30-instruction sequence
through the EE/EF region leading to `$EF6B STZ $72`. We then widened
by another 60 instructions upstream to find the entry point
(`CODE_00EDF7` entered via `JMP` from `CODE_00ED5B`).

**Why it matters:** We needed to know the actual JSR chain on oracle
to cross-reference with recomp's gen'd code. Without the hardware
insn trace, we'd only know "oracle wrote $72 at PC $EF6D" — we'd have
to manually disassemble and reason about which caller got there.

**Why this wasn't doable before:** The insn-trace infrastructure
existed in `snes9x_bridge.cpp` for a while but had been exercised
only with small test cases. This session used it at scale — 371k
insns in one capture, demonstrating the ring is sufficient for
moderate-window investigations.

### 7. `find_first_divergence` WRAM comparator

`find_first_divergence wram 0x<lo> 0x<hi> <context>`

Side-by-side byte comparison of recomp's `g_ram` and oracle's WRAM,
returns the first offset where they differ plus a context window.

**Use:** narrow-range scans across `$0070-$009F` at mode-entry
confirmed the divergence shape in seconds. Used as the fast
"is-this-already-fixed?" check when testing hypothesized fixes.

**Why it matters:** Without this, you'd dump both sides' full WRAM
and grep-diff the hex — slow and loses context about what address
means what.

## What we could NOT find before this tool stack existed

1. **"Which ROM instruction cleared $72 on oracle but not recomp"** —
   impossible without (a) an embedded emulator oracle (snes9x via
   `s9x_write_hook`) and (b) recomp's own Tier-1 `trace_wram` with
   old/new capture. The previous-generation debugging used smw-rev,
   a hand-decompilation, which can't tell you "this specific ROM PC
   writes this byte."

2. **"Is $72's wrong value at mode-0x07 entry the root or just a
   downstream symptom?"** — answered by state-synced dwell=0 diff.
   Without state-sync the divergence list is huge (46 items in the
   v2 golden fixture) and one can't pick a seed.

3. **"Does recomp actually execute the same ROM-level call chain as
   oracle during level-load?"** — answered by pairing recomp's
   `trace_calls` (Tier 1.5) with oracle's `emu_insn_trace`. Neither
   alone is sufficient: trace_calls tells you who was pushed in
   recomp, insn_trace tells you what PC ran on oracle.

4. **"Is the function attribution in trace_wram reliable?"** — only
   discoverable by snapshotting the full recomp stack at a watch hit
   and seeing 39-deep stacks full of leaked entries. Without the
   extended `parked` we'd still be following wrong `writer` names.

5. **"Why is mode 0x03 one frame on recomp but 20 on oracle — is that
   a bug?"** — answered by the GameMode timeline plus the insn-trace
   showing oracle burns those 20 frames on cycle-accurate CPU work,
   not waiting for NMI. Recomp's collapsed timing is semantically
   equivalent. Without both tools we'd likely have wasted a session
   trying to "fix" the timing.

## Anti-patterns this investigation rejected

- **Asking smw-rev "what does it do here?"** — smw-rev is a
  hand-decompilation. We use ROM-accurate emulation now, not a
  separate interpretation of the game. SMWDisX is the literal-code
  oracle; snes9x is the behavioral oracle.
- **Printf debugging.** Zero printfs were added. Every observation
  went through the TCP structured interface.
- **Hand-editing gen'd code.** `smw_00_gen.c` was only READ, never
  modified. The bug is a codegen-path issue and must be fixed in
  `recomp.py`.
- **Trusting single-query results.** The 0-hit trace_calls queries
  looked definitive but were buffer-truncated. Multi-window pagination
  revealed the real picture.

## Next-session concrete plan

Per task #8: the remaining work is a `break_add` bisect inside
`RunPlayerBlockCode_EB77` (ROM $EB77 → $EE11 → $EE3A path). Set
breakpoints at every RDB_BLOCK_HOOK PC between $EB77 and $EE3A (about
~20 block entries), step once at mode-0x04 entry, observe which
break fires. Oracle reaches $EDF7 → $EE11 → $EE3A; recomp diverges
somewhere before $EE3A. The first missing break identifies the
divergence point.

## Key TCP commands used

| Command | Use |
|---|---|
| `dump_ram <addr> <n>` | Read recomp WRAM |
| `emu_read_wram <addr> <n>` | Read oracle WRAM |
| `step <n>` | Advance both sides lockstep |
| `emu_step <n>` | Advance oracle only (boot-timing sync) |
| `trace_wram <lo> <hi>` | Arm recomp Tier-1 write trace |
| `get_wram_trace` | Dump the recomp write log |
| `emu_wram_trace_add <lo> <hi>` | Arm snes9x bus-write hook |
| `emu_get_wram_trace` | Dump the oracle write log (PC, before, after) |
| `trace_calls` | Arm Tier-1.5 per-push call trace |
| `get_call_trace from=<f> to=<f> contains=<substr>` | Filter trace |
| `break_add <hex_pc>` | Tier-2.5 PC breakpoint |
| `watch_add <addr> [val]` | Tier-2.5 WRAM watchpoint |
| `parked` | Reports park reason, writer, and (new) full recomp stack |
| `emu_insn_trace_on/off/reset` | Oracle per-instruction trace arm |
| `emu_get_insn_trace pc_lo=.. pc_hi=.. limit=..` | Dump filtered insn trace |
| `find_first_divergence wram <lo> <hi> <context>` | WRAM byte-diff |

Every command lives under
`snesrecomp/runner/src/debug_server.c` (recomp side) or
`snesrecomp/runner/src/emu_oracle_cmds.c` (oracle side). Probe
scripts under `snesrecomp/tests/l3/_probe_bug8_*.py` demonstrate
usage patterns.
