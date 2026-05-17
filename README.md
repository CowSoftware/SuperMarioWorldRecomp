# SuperMarioWorldRecomp

Static recompilation of *Super Mario World* (SNES) into native C,
using the [snesrecomp](https://github.com/mstan/snesrecomp) framework.
This repo is the per-game side: the runtime, the recompiled C output,
the per-game `.cfg`, and the build glue.

## What "static recompilation" means here

The 65816 CPU code from the ROM is statically translated to C — every
function the game runs on the SNES's main CPU is a real generated C
function in `src/gen/`. **The rest of the SNES is not recompiled** —
it's hardware. PPU rendering, the APU / SPC700 audio coprocessor, DMA
and HDMA channels, hardware register I/O, and bank-mapping all run
through an embedded copy of snes9x's emulator core
(`snesrecomp/runner/snes9x-core/`). This is the same model other
static-recomp projects (N64Recomp, etc.) use: recompile the CPU,
emulate the silicon. If you expected the PPU and APU to be recompiled
too, they aren't — and a static recompiler can't recompile them
because the SNES PPU has no instruction stream and the SPC700 is a
separate processor with its own firmware that the cartridge uploads
to a separate chip.

## Current status: believed fully playable

Hand-verified end-to-end through:
- **Yoshi's Island (World 1)** including Iggy's castle boss.
- **Donut Plains (World 2)** end-to-end.
- **Vanilla Dome (World 3)** in progress at time of writing.

No catastrophic visible regressions surfaced through these worlds.
Two runtime tripwires (the M/X claim verifier and the
async-cpu->m_flag/x_flag-write detector) are armed at boot and have
not latched on the verified worlds. An off-rails event was captured
in `BufferScrollingTiles_Layer1_VerticalLevel_M1X1` during Donut
Plains castle (bank-out-of-range pointer read; runtime mirrors the
read to a safe location and gameplay continues) — see
[`ISSUES.md`](ISSUES.md) for the bucketed capture and the
`offrails_get` TCP query.

Worlds 4–7 and special content (Star Road, Special World) are not
yet hand-verified but are expected to play similarly. If you hit a
visible regression, please open an issue with a savestate and the
`offrails_get` / `mx_async_check_get` JSON snapshots.

Active development; expect:
- Some branches don't build; only `main` is guaranteed to build.
- Internal docs (`ISSUES.md`, `ENHANCEMENTS.md`) assume context.
- APIs and recompiler output change without notice.

See [`RELEASE.md`](RELEASE.md) for the latest release notes.

## Quick start (pre-built release)

1. Download the latest `SuperMarioWorldRecomp-windows-x64.zip` from
   [Releases](../../releases) and extract it.
2. Run `smw.exe`. On first launch a file picker asks for your
   **legally-obtained** Super Mario World (USA) ROM (`.sfc` / `.smc`).
   The path is remembered in `rom.cfg` next to the exe.
3. Edit `keybinds.ini` (auto-generated next to the exe on first run)
   to remap keys, then restart.

The ROM is **never** redistributed — supply your own dump.

## Controls (default `keybinds.ini`)

| SNES button | Default key |
|-------------|-------------|
| D-Pad       | Arrow keys |
| A           | X |
| B           | Z |
| X           | S |
| Y           | A |
| L           | C |
| R           | V |
| Start       | Enter |
| Select      | Right Shift |

Player 2 is unbound by default — fill in keys in `keybinds.ini` to
enable a second keyboard player.

**Xbox / PlayStation / Switch Pro controllers** are auto-detected via
SDL_GameController (XInput on Windows). Plug it in before launching,
or hot-plug after. Default Xbox mapping is **position-true**: the
physical button position matches a SNES pad — so Xbox A (south face)
sends SNES B, Xbox B (east face) sends SNES A. To rebind, edit the
`[GamepadMap]` section of `smw.ini` (auto-generated next to the exe
on first run); the recognized names and the full mapping table are
in [`CONTROLLER.md`](CONTROLLER.md).

System shortcuts (configured in `smw.ini`'s `[KeyMap]` section):

| Action          | Default     |
|-----------------|-------------|
| Save state 1-10 | Shift+F1..F10 |
| Load state 1-10 | F1..F10 |
| Toggle pause    | P |
| Reset           | Ctrl+R |
| Toggle fullscreen | Alt+Enter |
| Turbo (fast-forward) | Tab |
| Toggle renderer | R |
| Display perf    | F |

## Building from source

Prerequisites: Windows 10+, Visual Studio 2022 (with C++ desktop
workload), Python 3.9+ on PATH.

```bash
git clone --recurse-submodules https://github.com/mstan/SuperMarioWorldRecomp
cd SuperMarioWorldRecomp
```

The `snesrecomp/` directory is a [sibling repo](https://github.com/mstan/snesrecomp)
accessed via a junction/symlink. If you don't already have it checked
out next to this repo, clone it:

```bash
git clone https://github.com/mstan/snesrecomp ../snesrecomp
```

Then build:

```bash
# From a Developer Command Prompt for VS 2022, or with MSBuild on PATH:
msbuild smw.sln /p:Configuration=Release /p:Platform=x64 /m
```

The recompiled C in `src/gen/` and the `recomp/funcs.h` declarations
are committed and built directly — no ROM is required at build time.
Run the exe and the runtime ROM-picker handles the rest.

### Regenerating the recompiled C (contributors)

If you change anything under `recomp/bank_*.cfg`, the snesrecomp
framework, or otherwise need to re-run the recompiler:

1. Drop a legally-obtained `smw.sfc` at the repo root (`.gitignore`
   excludes it).
2. Run `bash tools/regen.sh`. This drives `snesrecomp/recompiler/`
   over the ROM and rewrites `src/gen/*.c`, `recomp/funcs.h`, and
   the per-bank registry.
3. Rebuild as above.

(Build and run instructions are not yet stable — see scripts under
`tools/` and notes in `docs/` for the current shape, but expect them
to drift.)

## Repo layout

- `src/` — runtime C (CPU state, runtime helpers, hand-written
  bodies for things the framework doesn't yet recompile).
- `src/gen/` — recompiler output (do not hand-edit).
- `recomp/` — per-bank `.cfg` files describing what the framework
  cannot yet derive from the ROM (data regions, calling conventions,
  rare hints).
- `snesrecomp/` — symlink to a sibling clone of the
  [snesrecomp framework](https://github.com/mstan/snesrecomp).
- `tools/` — build, regen, audit, and triage scripts.
- `docs/` — design / debugging notes (internal-facing, may be stale).
- `third_party/` — vendored deps with their own licenses.

## License

Not yet declared. Code in this repo is original; vendored
dependencies under `third_party/` retain their own licenses.

The SMW ROM and any data extracted from it are **not** in this
repo and are not licensed for redistribution.
