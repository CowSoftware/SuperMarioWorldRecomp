# Demo Desync Investigation — Findings (virtual-hw-timing branch)

**Status:** root cause is more nuanced than initial hypothesis. Logged here for the next session.

## Confirmed via empirical probing

1. **Demo phase IS synced at GM=$07 entry on both sides.** TitleInputIndex ($1DF4) = 0, VariousPromptTimer ($1DF5) = 1 on BOTH recomp and snes9x at first GM=$07 sighting. So Option D's premise (phase desync) was wrong — `demo_sync.py`'s `sync_demo_phase` reports `(rec +0, emu +0)` extra steps needed.

2. **Boot frame totals are nearly equal.** Both reach GM=$07 in ~204-208 emu_step / step calls. Per-stage counts:
   - recomp: GM=$00=5, GM=$01=64, GM=$02=29, GM=$03=1, GM=$04=1, GM=$05=32, GM=$06=75, total 207 to GM=$07.
   - snes9x: GM=$02=19, GM=$03=20, GM=$04=55, GM=$05=34, GM=$06=75, total 203 to GM=$07.
   - snes9x doesn't show GM=$00/$01 (skipped or absorbed into the first emu_step).
   - GM=$03/$04 collapse on recomp (1 frame each vs 20/55 on snes9x) — but offset by GM=$00/$01 only present on recomp.

3. **State at GM=$07 entry differs in 10 bytes (OAM/sprite buffers).** The 10 bytes are continuously-written sprite-rendering state (`GenericGFXRtDraw1Tile16x16`, `CompressOamEntExt`, `SetPlayerPose`, `GameMode14_InLevel`). Recomp DOES eventually write all of them (validated by `_probe_oam_post_gm07.py`: after +200 lockstep steps past GM=$07, recomp's $03EC-$049B etc. all populate). They just hadn't been written by recomp's GM=$07-first-sighting moment.

4. **Trace anomaly.** snes9x's WRAM-trace shows writes at frame numbers (e.g. f=296) HIGHER than the GM=$07 sync moment (frame 204). Two possibilities:
   - `s_watch_frame` is not incremented in the way assumed (need to add an `emu_frame` query command and verify).
   - snes9x's `retro_run` internally cycles multiple "internal frame ticks" per call.
   - Either way, the WRAM trace's `f` field doesn't directly equal "number of emu_step calls so far."

## Demo desync root candidates (still to discriminate)

### Candidate A: cycle-accuracy in busy-waits
- Recomp's GM=$03/$04 stages collapse to 1 frame each because SMW's busy-waits (DMA done, SPC handshake, $4212 hblank, etc.) terminate immediately on recomp.
- Counter-evidence: `g_main_cpu_cycles_estimate` is incremented per RDB_BLOCK_HOOK, and the SPC busy-wait loop at bank_00:8082 IS a real loop with block-hook firing each iteration. Cycle catchup math gives ~7 APU cycles per iteration, ~5000 over 700 iterations — should suffice. So either the math is wrong, the loop terminates before the SPC has caught up, or the SPC IPL isn't actually responding cycle-accurately.

### Candidate B: snes9x runs internal frames during init
- `snes9x_bridge_init` calls `retro_init` + `retro_load_game` + `snes9x_bridge_watch_add(0, 0x1FFFF)`. None of these explicitly call `retro_run`.
- BUT snes9x's CPU may auto-tick during reset/load. The first emu_step lands snes9x at GM=$02 (not GM=$00) which suggests SOME advancement during init.
- Counter-evidence: if snes9x ran 70 frames during init, the absolute `s_watch_frame` after our 1st emu_step would be ~71. The trace shows f=20 for the first $03E8 write (during boot zero-fill). That's plausible for "snes9x ran 20-cycle SMW boot during 1 emu_step" if retro_run loops to next vblank and SMW's first vblank is ~20 internal frames in.

### Candidate C: `s_watch_frame` semantics
- Need to verify what frame counter actually drives the trace `f` field. Add an `emu_frame` query command and re-run the OAM-residue probe to compare.

## Recommended next moves

1. **Add `emu_frame` TCP command** that returns `s_watch_frame`. Re-run boot-GM + OAM-residue probes; reconcile what `f` actually means.
2. **Per-stage SPC handshake instrumentation.** Trace every $2140-$2143 read+write during GM=$03/$04 on both sides. If recomp's busy-wait terminates after N iterations and snes9x's after M, with N ≪ M, the SPC pacing is the source. If N ≈ M, it's something else.
3. **GM=$04 deep-dive.** snes9x spends 55 frames here; recomp 1 frame. What is GM=$04's handler busy-waiting on? Read SMWDisX `GameMode04_PrepareTitleScreen` and identify the busy-wait condition.
4. **Reconcile the apparent contradiction.** Per-stage frame counts say recomp is FASTER (138 vs 203 in GM=$02-$06) but boot totals are nearly equal (208 vs 204). The arithmetic doesn't add up — recomp must be 65 frames faster after subtracting common 75-frame GM=$06, but the totals match. Likely a misread of the per-stage data; verify by re-running boot probe with raw frame counter dumps.

## What we KNOW works

- Phase-pin at GM=$07 entry (TitleInputIndex / VariousPromptTimer match).
- The 10 OAM bytes that differ at sync are sprite-render buffer state, NOT load-bearing for collision/physics. Mario's collision math doesn't read these.
- Cascade-divergence after +1 lockstep step (43 NEW byte diffs) is downstream of those 10 — confirmed by trace attribution.
