# SuperMarioWorldRecomp

Static recompilation of *Super Mario World* (SNES) into native C,
using the [snesrecomp](https://github.com/mstan/snesrecomp) framework.
This repo is the per-game side: the runtime, the recompiled C output,
the per-game `.cfg`, and the build glue.

> ## ⚠️ Heavily Work-In-Progress — NOT A PLAYABLE BUILD
>
> The recompiled binary boots and renders the title screen and attract
> demo, but **the game is not playable**. Active gameplay (entering a
> level, controlling Mario, completing a stage) has not been
> end-to-end verified and is **assumed broken**.
>
> Treat this repo as an in-progress engineering snapshot, not a
> release. Expect:
> - Branches that don't build.
> - Internal docs that assume context from active development.
> - APIs and recompiler output that change without notice.
> - Known visual and behavioral bugs even in the parts that "run."

## What works (sort of)

- Boot and title screen render.
- Attract-demo cinematic plays through and renders.

## Known visible bugs in the attract demo

Even the parts that render have moderate visible bugs:

- Berries render with the wrong palette (appear as `?` blocks).
- Some enemies are missing entirely.
- Some enemies are invisible but still interact (stompable, etc.).
- `?` blocks do not respond to being hit.
- Physics on sloped surfaces is incorrect (Mario sinks / mis-aligns).

This list is non-exhaustive — additional bugs almost certainly exist
in code paths the attract demo doesn't exercise.

## In-game gameplay

**Not verified.** Past the attract demo, no part of the game has been
manually played end-to-end. Anything beyond "the screen renders"
should be assumed to be broken.

## Building / running

You need to bring your own **legally-obtained** Super Mario World ROM
(`smw.sfc`) and place it at the repo root. ROMs are explicitly
excluded from this repo via `.gitignore`. The build pipeline reads
the ROM, recompiles it via snesrecomp, and links the output into a
native executable.

(Build and run instructions are not yet stable — see internal docs
under `docs/` and the build scripts under `tools/` for the current
shape, but expect them to drift.)

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
