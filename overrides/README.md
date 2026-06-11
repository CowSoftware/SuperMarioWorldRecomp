# Override layer (optional behaviour extensions)

This folder is an **opt-in plugin layer** that extends the recompiled game
beyond authentic SNES behaviour. It exists *outside* `src/gen/` on purpose:

- `src/gen/` is regenerated from the ROM by snesrecomp and must never be
  hand-edited (edits there are lost on every regen).
- Overrides here are **re-applied to the freshly generated banks at build
  time** by `tools/apply_overrides.py`, so they survive regen.

Nothing here changes snesrecomp's defaults. Every override is gated on a
runtime flag (`g_ws_active`, fed from the `Widescreen` config option). With
the flag off the original generated code path runs unchanged — the build is
byte-for-byte authentic.

## How it works

1. `apply_overrides.py` reads a manifest (e.g. `widescreen/overrides.manifest`).
2. For each targeted generated function it injects a guarded dispatch prologue
   immediately after the function's opening brace:

   ```c
   RecompReturn SomeFunc_M1X1(CpuState *cpu) {
     { extern bool g_ws_active; extern RecompReturn Override_SomeFunc(CpuState *cpu);
       if (g_ws_active) return Override_SomeFunc(cpu); }
     /* ... original generated body ... */
   }
   ```

   Injection is **idempotent** (marked with `/*WS-OVERRIDE*/`) and re-applied
   every build, so it is safe to run after every regen.
3. The override implementations live in `widescreen/*.c` and are compiled into
   the game binary.

## Contract for override implementations

- An override **fully replaces** the targeted function while `g_ws_active` is
  true. It must NOT call the same generated function (that would re-enter the
  injected prologue and recurse). If you only need to tweak a constant, copy
  the original body into the override with the constant changed — the copy
  lives here, outside `src/gen/`, so it is durable.
- One override is routed from *all* `(m,x)` width-mode variants of the named
  function. If a variant needs different handling, read the mode from
  `cpu->P` inside the override, or list the specific variant in the manifest.

## Manifest format

`widescreen/overrides.manifest`, one rule per line:

```
# base_function_name            -> override_symbol            [variant]
IsOffScreenBnk2                 -> Override_IsOffScreenBnk2
ParseLevelSpriteList_Entry2     -> Override_ParseLevelSpriteList_Entry2
```

- `base_function_name` matches every `<base>_M?X?` definition in `src/gen/`.
- Optional trailing `variant` (e.g. `M1X1`) restricts the rule to one variant.
- Lines starting with `#` and blank lines are ignored.
