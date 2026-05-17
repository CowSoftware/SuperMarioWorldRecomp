# v0.3.0 — Playable

First milestone where the game is **playable** end-to-end from boot through gameplay. Not exhaustively tested, but every step on the golden path works.

## What works

- **Attract demo** — frame-perfect, no observable drift through full attract loop (carried over from v0.1.0, still holds).
- **Menu chain** — title → 1-Player Game → file-select (MARIO A/B/C) → intro cutscene → first level — every Start press lands cleanly.
- **Save persistence** — in-game save writes to `saves/smw.srm` on graceful window close and reloads on next launch. SRAM survives across runs (3-slot file-select restores the player's progress).
- **Overworld** — Yoshi's Island map renders correctly with proper terrain, paths, level icons, and the player border. Mario can navigate between nodes.
- **First-world stages** — at least 4 stages playable end-to-end by manual playthrough. No reproducible regressions in the golden path.

## Caveats

- Only the first world has been hand-tested. Worlds 2–7, Star World, Special World, and any switch-palace mechanics are not verified.
- No automated regression suite for in-game gameplay — verification is human visual play.
- Building requires a local SMW ROM (CRC checked at startup); CI cannot build.

## Notable fixes since v0.1.0

- **MVN / MVP block-move src/dst swap** — the recompiler was emitting block-moves backwards (RAM→ROM no-op), so the overworld Map16 buffer kept stale `$25` data and the map rendered as repeating fence stripes. Class fix at the lowering level; all 9 MVN/MVP sites now correct. This was the root cause of overworld corruption *and* of Mario being "stuck on an invalid tile" *and* of the wrong-destination on A-press — one bug, three visible symptoms.
- **TCP screenshot freezing the visible window** — `cmd_screenshot` rebound `g_ppu->renderBuffer` to a local scratch buffer and never restored it. After the first TCP screenshot, every main-loop frame rendered into the scratch and the SDL texture stayed frozen on the last visible image. Save/restore around the rebind.
- **SRAM read/write routing** — LoROM `$70-$7D` and HiROM `$00-$3F:6000-7FFF` SRAM accesses now route to `g_sram` via the snes9x cart mapping, unblocking the save chain that was previously falling through to invalid `RomPtr` reads.
- **Leaf exit-(M, X) auto-routing pass 2** — the auto-router now detects multi-variant convergent leaf functions (closes the "cfg-declared entry is non-mutating, other entries mutate" class).
- **NLR detector case (d)** — handles `PLA*N` at block-start + branching-tail. Caught `HandleMenuCursor_9ACB` and `RunPlayerBlockCode_00EFE8_ReturnsTwice`.

## Install

1. Extract the zip.
2. Place a verified Super Mario World ROM (`smw.sfc`) anywhere on disk.
3. Run `smw.exe`; first launch prompts for the ROM path and caches it in `rom.cfg`.
4. Saves land in `saves/smw.srm` (created automatically).

## Components in this release

- `smw.exe` — Oracle x64 build (includes the always-on observability rings for debugging; same gameplay path as Release).
- `SDL2.dll` — required runtime.
- `keybinds.ini` — default controller mapping.
