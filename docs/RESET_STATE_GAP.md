# Reset-State Gap: snes9x core vs recomp's minimal SNES core

Date: 2026-04-24
Branch: koopa-stomp-next
Audience: this is research feeding Phase A.6 (uninitialized-WRAM audit) so we can re-land
`memset(g_ram, 0x55, 0x20000)` without segfaulting at +60 frames.

## Why this exists

Last session confirmed empirically that initializing `g_ram` to `0x55` instead of `0x00` at
power-on collapses a recomp-vs-snes9x WRAM divergence from **8188 bytes → 6 bytes** at +5 frames
of attract demo. The recomp build then segfaulted at +60 frames — at least one generated site
reads uninitialized WRAM and uses the value as a pointer or jump target, which `0x00` init
silently masked (NULL-deref protection by BSS zero) but `0x55` (→ `0x5555…`) does not.

So the question is: *what state does snes9x set at reset that recomp does not?* The answer
narrows where to look for the unsafe-pointer reads.

## Side-by-side comparison

| Subsystem | snes9x reset | recomp reset | Gap |
|---|---|---|---|
| WRAM `$0000-$1FFFF` | `memset(0x55, 0x20000)` — `cpu.cpp:101` | `memset(0, 0x20000)` — `snes.c:69` | **Critical.** Recomp zero-fills; real hardware/snes9x uses `0x55`. Empirically confirmed: switching to 0x55 cuts +5-frame WRAM diff 8188 → 6. |
| VRAM `$0-$7FFF` | `memset(0)` — `cpu.cpp:102` | implicit zero via `ppu_reset` memset — `ppu.c:36` | Match |
| CGRAM | zero via FillRAM, then `S9xSoftResetPPU` recalc — `ppu.cpp:1783` | implicit zero via `ppu_reset` memset | Match |
| FillRAM `$2100-$21FF` (PPU MMIO shadow) | `memset(0, 0x100)` — `ppu.cpp:1922` | no shadow exists; reads/writes route through handlers | Recomp lacks an MMIO shadow array. If gen code reads `$2100-$21FF` directly via `g_ram[]` rather than through `snes_readReg`, it sees BSS-zero, not snes9x's explicit zero (same value but different *source*). |
| FillRAM `$4200-$42FF` (CPU MMIO shadow) | `memset(0, 0x100)` then writes 0xFF to `$4201`, `$4213` — `ppu.cpp:1923, 1928` | no shadow | Same shape. Recomp's `$4201` / `$4213` are not pre-set to 0xFF. |
| FillRAM `$4000-$40FF` | `memset(0, 0x100)` — `ppu.cpp:1924` | no shadow | Same shape. |
| CPU registers (A/X/Y/S/PC/DP/DB/PB/P) | `S9xResetCPU` + `S9xSoftResetCPU` — `cpu.cpp:24-95` | `cpu_reset` — `cpu.c:31-49` | Match: A/X/Y=0, SP=0x100, DP=0, DB=0, PB=0, M/X=1, I=1, E=1, D=0. (Recomp doesn't fetch the reset vector — it jumps directly to recompiled entry.) |
| DMA channels | `S9xResetDMA` — `dma.cpp:1614-1635` (all 8: ReverseTransfer=1, AAddressFixed=1, BAddress=0xFF, AAddress=0xFFFF, ABank=0xFF, DMACount=0xFFFF, …) | `dma_reset` — `dma.c:40-64` (same defaults) | Match |
| PPU.VMA | `Address=0, Increment=1, Shift=0` — `ppu.cpp:1756` | `vramPointer=0, vramIncrement=1` — `ppu.c:40` | Match |
| PPU.OAM | OAMData zeroed, OAMAddr=0 — `ppu.cpp:1815` | implicit zero via `ppu_reset` memset | Match |
| PPU BG[0..3] regs | zero — `ppu.cpp:1766-1772` | implicit zero | Match |
| PPU forced-blank flag | `ForcedBlanking=TRUE` — `ppu.cpp:1868` | recomp has `inidisp=0`, no explicit forced-blank bit set | **Gap.** Recomp leaves `inidisp=0x00` after reset, snes9x effectively starts in forced-blank state. Likely benign for SMW since first real frame writes `$2100`. |
| IRQ/NMI timer state | `HTimerEnabled=FALSE, IRQHBeamPos=0x1FF, IRQVBeamPos=0x1FF` — `ppu.cpp:1821` | `Snes.hIrqEnabled=false, hTimer=0x1FF, vTimer=0x1FF` — `snes.c:74` | Match |
| APU/SPC reset | `S9xResetAPU` runs full `smp.power()` — `apu.cpp:304` (executes IPL bootrom seal loop, ~10k cycles) | `apu_reset` zeroes regs + `spc_reset` — `apu.c:35`, `spc.c:67` (no IPL simulation) | **Gap.** Recomp skips the IPL-bootrom warmup. APU timers may tick at a different absolute offset for the first ~160 frames. Probably not the koopa-stomp cause but flagged for audio investigation. |
| APU RAM | inherited zero from FillRAM | `memset(apu->ram, 0)` — `apu.c:39` | Match |
| Joypad shadow (`$4016/$4017`) | `S9xControlsSoftReset` — `controls.cpp:392` (FLAG_LATCH=FALSE, controller state reset) | not shadowed; recomp reads from `snes->input1_currentState` per call | Recomp doesn't model the auto-read sequence shape. Closed in this session for the falling-through-to-`g_ram[]` case (commit `bfb8b40` snesrecomp); confirm no new gap re-opens. |
| OpenBus | set to `PCh` after reset vector fetch — `cpu.cpp:65` | not tracked | Recomp returns 0x00 for unmapped reads. Likely insignificant for SMW. |
| Multiply/divide regs (`$4202-$420A`) | not reset by snes9x; inherits state | recomp explicitly sets `multiplyA=0xFF, multiplyResult=0xFE01, divideA=0xFFFF, divideResult=0x101` — `snes.c:85` | **Gap (inverted).** Recomp initializes specific values that snes9x doesn't. If the recomp values match real-hardware power-on, recomp is *more* correct here; if they don't, recomp is wrong. **Action: verify against fullsnes / anomie.** |

## Top gaps (priority order for closing)

Filtered to "most likely to affect WRAM/control-flow divergence in first ~100 frames of attract demo":

1. **WRAM fill pattern (recomp 0x00 vs snes9x 0x55)** — `snes.c:69`. Empirically the highest-impact single fix. Blocked on the +60-frame segfault → Phase A.6 audit.

2. **APU IPL bootrom not simulated** — `spc.c:67`. Causes APU timers to tick at a different absolute time-base. Won't directly cause WRAM divergence in CPU-side code; flagged for audio.

3. **`$2100` INIDISP forced-blank bit not set** — `ppu.c:36`. Recomp starts at `inidisp=0x00`, snes9x effectively at forced-blank. Likely benign because the game writes `$2100` early in init, but worth a one-line fix for parity.

4. **Multiply/divide register power-on state** — `snes.c:85`. Recomp sets specific values; verify these are correct against fullsnes. If wrong, this could cause early-init divergence on any game that reads `$4216/$4217` before writing.

5. **`$4201` WRIO not set to 0xFF** — recomp leaves at 0x00. Joypad I/O pin defaults; likely benign for SMW.

(Items 6-10 from the research pass — joypad state, OpenBus, beam latches, DMA channels — are either already matching or unlikely to bite SMW.)

## Action items

- [ ] **Phase A.6** — audit recomp gen sites that read WRAM and use the value as a pointer / address / jump target without explicit init. Each must be initialized in the SMW reset path (or guarded). This unblocks #1.
- [ ] After A.6: re-land `memset(g_ram, 0x55, 0x20000)` in `snes.c:69`. Verify: framework tests + fuzz green, +60-frame run no segfault, attract demo plays, hand exe to user for visual.
- [ ] Verify multiply/divide power-on state (#4) against `problemkaputt.de/fullsnes.htm`. If wrong, fix in `snes.c`.
- [ ] One-line: set `inidisp` forced-blank bit at PPU reset (#3). Cheap parity win.
- [ ] (Audio investigation, separate branch) IPL bootrom simulation (#2).

## Source references

snes9x:
- `snesrecomp/runner/snes9x-core/cpu.cpp:97-132` — `S9xReset` master entry
- `snesrecomp/runner/snes9x-core/cpu.cpp:24-95` — `S9xResetCPU` / `S9xSoftResetCPU`
- `snesrecomp/runner/snes9x-core/ppu.cpp:1750-1929` — `S9xResetPPU` / `S9xSoftResetPPU`, FillRAM init
- `snesrecomp/runner/snes9x-core/dma.cpp:1614-1635` — `S9xResetDMA`
- `snesrecomp/runner/snes9x-core/apu/apu.cpp:304-315` — `S9xResetAPU`
- `snesrecomp/runner/snes9x-core/controls.cpp:392-406` — `S9xControlsSoftReset`

recomp:
- `snesrecomp/runner/src/snes/snes.c:62-89` — `snes_reset` (master)
- `snesrecomp/runner/src/snes/cpu.c:31-49` — `cpu_reset`
- `snesrecomp/runner/src/snes/ppu.c:32-41` — `ppu_reset`
- `snesrecomp/runner/src/snes/dma.c:40-64` — `dma_reset`
- `snesrecomp/runner/src/snes/apu.c:35-52` — `apu_reset`
- `snesrecomp/runner/src/snes/spc.c:67-83` — `spc_reset`
- `snesrecomp/runner/src/snes/dsp.c:73+` — `dsp_reset`
- `snesrecomp/runner/src/common_cpu_infra.c` — search for `g_ram` init (none expected at runtime; static BSS only)
