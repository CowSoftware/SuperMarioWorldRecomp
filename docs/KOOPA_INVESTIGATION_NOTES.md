# Koopa-stomp investigation — research notes

## Visible bug (still open)

In the SMW attract demo, recomp's Mario contacts the koopa from the
side and dies, instead of stomping it from above. Everything before
contact looks fine; the divergence is small but compounds over ~260
frames into a wrong-angle collision.

## What I know

### Frame-zero state
At first-call to `HandlePlayerPhysics` ($00:$D5F2), exactly one byte
diverges: `$0DA0` (`ControllersPresent`). **CLOSED 2026-04-24** —
fix at `recomp.py` `_is_hw_reg` + `common_rtl.c::ReadReg` +
`snes/snes.c::snes_readReg` to dispatch `$4016`/`$4017` correctly.
SMW reads JOYSER0/1 as part of the manual joypad-detect routine at
`CheckWhichControllersArePluggedIn` ($00:$9A74); recomp was reading
g_ram instead of MMIO, returning 0 instead of the controller-present
signature, so SMW concluded "no controllers" and wrote `$0DA0=$00`
instead of `$82`.

### Frame-one onward (open)
At call 2 onwards, new bytes diverge:
- `$14A2 CapeAniTimer` — recomp=0, oracle=7
- `$1DFF LastUsedMusic` — recomp=1, oracle=0
- `$13DF PlayerCapePose` (call 3+) — recomp=5, oracle=0
- `$1491 SpriteXMovement` (call 3+) — recomp=0, oracle=$FF
- `$8A`, `$98`, `$9A` (call 21+) — Mario physics scratch

The frame elapsed between call 1 and call 2 differs:
- Recomp: 106 frames between calls 1 and 2.
- Oracle: 110 frames.

Meaning between call 1 (logical state matched) and call 2, the two
sides took different control-flow paths through the GameMode
dispatcher. The 4-frame discrepancy compounds into the visible bug.

## Whack-a-mole risk

Each remaining diverging byte is plausibly a different framework
gap (different MMIO read, different RAM region, different
init order). Fixing them one-by-one is not converging fast.

## Research tasks (this branch)

Want to understand at a higher level WHAT snes9x initializes that
recomp doesn't. Specifically:

1. **WRAM init pattern.** snes9x fills with `0x55`. Recomp leaves
   BSS-zero. Tried memset(g_ram, 0x55) — recomp segfaults at +60
   frames because some uninitialized-WRAM-as-pointer dereference
   that was masked by NULL becomes `0x5555` (bad pointer).
   Phase A.6 audit needed: find every recomp gen site that reads
   WRAM as a pointer without explicit init, and ensure the init
   happens before the read.

2. **MMIO register init.** What does snes9x set in `Memory.FillRAM`
   ($2100-$5FFF)? In `PPU.*` fields? In `CPU.*` fields? Some of
   these affect what subsequent ROM reads return, and SMW reads
   them during boot.

3. **Comparison with other recompilers.** zelda3 (snesrev) does
   something similar at boot. nesrecomp embeds Nestopia. How do
   they avoid this divergence class?

4. **SNES powerup state documentation.** Anomie's SNES docs and
   fullsnes describe what's defined vs what's "undefined" at
   powerup. Some bytes have well-defined values; others (DRAM
   refresh, controller serial, ...) genuinely aren't deterministic.

## What I'm looking for

Three layers of finding:

1. **Hard fact:** "snes9x writes value V to WRAM byte X / MMIO reg Y
   at boot. Recomp doesn't. SMW reads X/Y during init and depends
   on V." → fix recomp to also write V.

2. **Pattern:** "snes9x's reset path includes step Q (e.g. apu_init,
   ppu_reset). Recomp's path has a structurally different equivalent
   that doesn't write the same outputs." → identify the gap.

3. **Limitation:** "This is genuinely undefined hardware state. Real
   SNES units differ from each other on this byte. snes9x picked one
   value; recomp picked another. SMW happens to read it. Decision:
   match snes9x, document as `pinned to snes9x convention`."
