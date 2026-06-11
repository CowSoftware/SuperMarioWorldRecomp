#include "smw_rtl.h"
#include "variables.h"
#include "common_cpu_infra.h"
#include "snes/snes.h"
#include "snes/ppu.h"
#include "cpu_state.h"
#include "funcs.h"
#include "debug_server.h"
#include "cpu_trace.h"

// Widescreen master switch + border half-width (per side), defined in main.c.
extern bool g_ws_active;
extern int g_ws_extra;

// Widescreen OAM x-high fixup (opt-in; no-op when widescreen is off).
//
// The SNES OAM x is 9-bit: a low byte plus one x-high bit. SMW's general OAM
// path (FinishOAMWrite) sets the x-high bit for any tile off the 256-wide
// screen, which — with the PPU's widened sprite-x wrap threshold — places
// left- and right-margin sprites correctly. But some special sprites (e.g.
// Yoshi) write OAM x WITHOUT that bit, so in widescreen a sprite whose true
// screen position is just off the LEFT (negative) instead renders at +low on
// the wrong (right) side: the classic 9-bit wrap ambiguity (screen-x -20 and
// +236 share a low byte).
//
// The game still holds each sprite's true 16-bit position in its sprite
// tables, so re-derive the x-high bit from the true sign. We run after OAM DMA
// has populated g_ppu->oam/highOam and before line rendering, and only ADD the
// x-high bit to left-margin tiles that are missing it — right-margin tiles
// (already correct) and on-screen tiles are left untouched. The per-tile
// reconstruction is self-correcting, so an over-wide tile window is safe.
static int g_ws_dbg = 0;
static void WidescreenFixupOamXHigh(void) {
  if (!g_ws_active)
    return;
  uint16 cam = *(uint16 *)(g_ram + 0x1A);  // mirror_current_layer1_xpos
  FILE *dbg = (g_ws_dbg < 2 && cam > 200) ? fopen("_ws_fixup.log", "a") : NULL;
  if (dbg) fprintf(dbg, "--- fixup call %d cam=%d ---\n", g_ws_dbg, cam);
  for (int k = 0; k < 22; k++) {           // sprite slots (main + a margin)
    if (g_ram[0x14C8 + k] == 0)            // spr_status: skip inactive
      continue;
    int origin_sx = (int16)((g_ram[0x00E4 + k] | (g_ram[0x14E0 + k] << 8)) - cam);
    int base = g_ram[0x15EA + k] >> 2;     // spr_oamindex is a byte offset; /4 -> OAM slot
    if (dbg) {
      int s0 = base, low0 = g_ppu->oam[s0 * 2] & 0xFF, y0 = (g_ppu->oam[s0 * 2] >> 8) & 0xFF;
      int xh0 = (g_ppu->highOam[s0 >> 2] >> ((s0 & 3) * 2)) & 1;
      fprintf(dbg, "  k=%2d stat=0x%02x sx=%d oamidx=0x%02x slot=%d tile0(low=%d y=%d xhigh=%d)\n",
              k, g_ram[0x14C8 + k], origin_sx, g_ram[0x15EA + k], base, low0, y0, xh0);
    }
    if (origin_sx >= 0)                    // only left-of-screen sprites can wrap to the right
      continue;
    for (int t = 0; t < 16; t++) {
      int slot = base + t;
      if (slot >= 128)
        break;
      int low = g_ppu->oam[slot * 2] & 0xFF;
      // Reconstruct this tile's true screen-x near the sprite origin.
      int tile_sx = origin_sx + (int8)(low - (origin_sx & 0xFF));
      if (tile_sx < 0 && tile_sx >= -g_ws_extra)
        g_ppu->highOam[slot >> 2] |= (uint8)(1 << ((slot & 3) * 2));  // set x-high
    }
  }
  if (dbg) { fclose(dbg); g_ws_dbg++; }
}

void SmwDrawPpuFrame(void) {
  WidescreenFixupOamXHigh();

  SimpleHdma hdma_chans[3];

  Dma *dma = g_dma;

  dma_startDma(dma, mirror_hdmaenable, true);

  SimpleHdma_Init(&hdma_chans[0], &dma->channel[5]);
  SimpleHdma_Init(&hdma_chans[1], &dma->channel[6]);
  SimpleHdma_Init(&hdma_chans[2], &dma->channel[7]);

  int trigger = g_snes->vIrqEnabled ? g_snes->vTimer + 1 : -1;

  for (int i = 0; i <= 224; i++) {
    ppu_runLine(g_ppu, i);
    SimpleHdma_DoLine(&hdma_chans[0]);
    SimpleHdma_DoLine(&hdma_chans[1]);
    SimpleHdma_DoLine(&hdma_chans[2]);
    //    dma_doHdma(snes->dma);
    if (i == trigger) {
      // Simulate hardware IRQ latch: I_IRQ's first instruction reads HW_TIMEUP
      // ($4211) and branches on the N flag to distinguish timer-IRQ from
      // other sources. recomp_hw.c's ReadReg(0x4211) returns g_snes->inIrq<<7
      // and clears the flag; assert it here so the handler takes the
      // timer-IRQ path instead of exiting immediately.
      g_snes->inIrq = true;
      /* Option-1 cpu->S ABI: model the hardware IRQ-entry push so I_IRQ's
       * terminal RTI pops a real interrupt frame. Without it RTI over-pops
       * (3 bytes emulation / 4 native) and cpu->S leaks every IRQ. Matches
       * mmx_rtl.c; see cpu_push_interrupt_frame in cpu_state.h. */
      cpu_push_interrupt_frame(&g_cpu);
      I_IRQ(&g_cpu);
      trigger = g_snes->vIrqEnabled ? g_snes->vTimer + 1 : -1;
    }
  }
}

void RunOneFrameOfGame(void) {
  // First-call reset gate. Was previously `if (*(uint16*)$7F8000 == 0) I_RESET()`,
  // which silently relied on WRAM being zero-initialized at power-on. Real hardware
  // (and snes9x) power-on WRAM is 0x55, so that check would never fire and I_RESET
  // would be skipped, leaving $0100 (GameMode) at 0x55 — out-of-bounds for the
  // 42-entry dispatch table at PC 0x009329. Use a host-side bool instead so the
  // gate is independent of WRAM contents.
  static bool g_did_reset = false;
  static bool g_first_frame_done = false;
  if (!g_did_reset) {
    cpu_state_init(&g_cpu, g_ram);
    cpu_trace_px_breadcrumb(&g_cpu, 0x1000, "after_cpu_state_init");
    I_RESET(&g_cpu);
    cpu_trace_px_breadcrumb(&g_cpu, 0x1001, "after_I_RESET");
    g_did_reset = true;
  }
  cpu_trace_px_breadcrumb(&g_cpu, 0x2000, "before_NMI_or_Internal");
  // NMI handler runs BEFORE the main-loop game code each frame.
  //
  // On real hardware NMI fires at vblank start (between frames).
  // Its handler polls HW_JOY ($4218/$4219) into the $15-$18 mirror;
  // the next frame's game logic reads that mirror. Demo inputs are
  // applied INSIDE the main loop by overwriting $15/$16; if NMI's
  // poll runs LAST it clobbers the demo bytes with the empty
  // controller state ($00) and the end-of-frame mirror reads as 0.
  //
  // Per snes9x oracle trace at GM=07: emu's per-frame writer order
  // is poll($86B2/$86C1) → DamagePlayer($F62F/$F631) → GameMode07
  // demo-override($9C93/$9C9C); demo bytes are LAST and stick. With
  // recomp's prior `Internal(); auto_00_816A()` order, PollJoypad
  // ran last instead, leaving $15/$16=$00. End-of-frame snapshot
  // diverges from oracle, and demo timing skews because the
  // VariousPromptTimer / TitleInputIndex tick keys off observable
  // input state.
  //
  // Frame 0 is special: real hardware fires the first NMI AFTER
  // I_RESET completes AND the main loop has had time to set up flags
  // (notably SEP #$10 → x=1). If we run I_NMI before Internal on the
  // very first frame, I_NMI's PHP captures I_RESET-end's P (x=0); its
  // RTI then restores x=0 to the main loop. Subsequent ProcessGameMode
  // → UploadGraphicsFiles_Layer3 → TAY at $00:A9A5 then runs as 16-bit,
  // copying A's polluted high byte into Y, indexing past the GFX bank
  // table and writing $7E (instead of $0B) to $7E:008C. Skip I_NMI on
  // frame 0 so the order matches hardware: I_RESET → main loop →
  // (vblank) → I_NMI → main loop → ...
  // Assert NMI-pending so the recompiled NMI handler's read of $4210
  // (RDNMI) returns bit 7 = 1, matching real hardware. snes_readReg
  // clears the latch on read.
  if (g_first_frame_done) {
    g_snes->inNmi = true;
    /* Option-1 cpu->S ABI: model the hardware NMI-entry push so I_NMI's
     * terminal RTI pops a real interrupt frame. Without it RTI over-pops
     * (4 bytes native) and cpu->S leaks +4 every NMI — the dominant
     * cause of SMW's per-frame stack drift into DMA-reg space. Matches
     * mmx_rtl.c; see cpu_push_interrupt_frame in cpu_state.h. */
    cpu_push_interrupt_frame(&g_cpu);
    I_NMI(&g_cpu);
    cpu_trace_px_breadcrumb(&g_cpu, 0x2001, "after_I_NMI");
  }
  cpu_trace_px_breadcrumb(&g_cpu, 0x2002, "before_Internal");
  /* Rearm the P.X tripwire here so the first x=1→0 transition INSIDE
   * Internal() (the main game loop) is captured fresh. The earlier
   * boot-time REP #$38 in I_RESET is expected and intentional; we only
   * want to know where x flips during ProcessGameMode dispatch. */
  cpu_trace_arm_px_tripwire();
  RunOneFrameOfGame_Internal();
  cpu_trace_px_breadcrumb(&g_cpu, 0x2003, "after_Internal");
  g_first_frame_done = true;
}

