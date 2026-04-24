#include "smw_rtl.h"
#include "variables.h"
#include "common_cpu_infra.h"
#include "snes/snes.h"
#include "funcs.h"
#include "debug_server.h"

void SmwDrawPpuFrame(void) {
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
      I_IRQ();
      trigger = g_snes->vIrqEnabled ? g_snes->vTimer + 1 : -1;
    }
  }
}

void SmwRunOneFrameOfGame(void) {
  if (*(uint16 *)reset_sprites_y_function_in_ram == 0)
    I_RESET();
  // NMI handler runs BEFORE the main-loop game code each frame.
  //
  // Rationale — hardware timing: on real SNES, NMI fires at vblank
  // start (between frames). Its handler polls HW_JOY ($4218/$4219)
  // into the $15-$18 mirror. The NEXT frame's game logic then reads
  // that mirror for player input. In the attract demo, the game
  // logic OVERWRITES $16 with a scripted demo input before Mario's
  // physics reads it; that overwrite must be the LAST write in the
  // frame, else Mario's input reverts to the HW-poll value (0).
  //
  // Previously this loop was `internal(); nmi();` — the NMI's
  // joypad poll ran AFTER the demo write each frame, stomping the
  // demo's $0x81 with 0 and leaving Mario with no input. Visible
  // symptom: Mario never accelerates or jumps in the attract demo,
  // koopa walks into him and "kills" him (no stomp input), demo
  // transitions to gameover/respawn. Diagnosed 2026-04-24.
  auto_00_816A();
  SmwRunOneFrameOfGame_Internal();
}

