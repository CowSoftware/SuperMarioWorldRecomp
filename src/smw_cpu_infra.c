#include "common_cpu_infra.h"
#include "smw_rtl.h"
#include "snes/snes.h"
#include "variables.h"
#include "funcs.h"
#include "assets/smw_assets.h"

extern bool g_custom_music;

static const uint32 kPatchedCarrys_SMW[] = {
  0xFE1F,
  0xFE26,
  0xFE35,
  0x1807a,
  0x18081,
  0x1A2CC,
  0x1B066,
  0x0fe79,
  0x0fe80,
  0x0fe88,

  0x1DDFB,
  0x1E0DD,
  0x2AAFB,
  0x2B05B,
  0x2B0A2,
  0x2B0A4,
  0x2B1DD,
  0x2B29B,
  0x2B2F6,
  0x3AD9B,
  0x498A2,
  0x2FBF5,
  0x2FBF7,
  0x2FC11,
  0x2FC13,
  0x2FC34,
  0x2FBFA,
  0x1D021,
  0x1D028,
  0x1B182,
  0x1FDD6,
  0x2B368,
  0x2BB3E,

  0x2C061,
  0x2C06C,
  0x2AD15,
  0x02DDA1,

  0x0399DB,

  0x1BC75,
  0x1BC78,
  0x1BC7A,
  0x2B228,

  0x2f231,
  0x2f23d,
  0x2f245,

  0x3C073,
};

static uint8 preserved_db;

static uint32 get_24(uint32 a) {
  return *(uint32*)SnesRomPtr(a) & 0xffffff;
}

uint32 PatchBugs_SMW1(void) {
  // Surviving entries are HLE/runtime bridges, NOT bug fixes:
  //   - DB-preservation around an HLE call boundary (0x1C641/0x1C644)
  //   - HLE replacement for CheckWhichControllersArePluggedIn (0x9A74)
  //   - HLE SPC skip for HandleSPCUploads entries (0x811D, 0x80F7)
  //     — these skip the body ONLY under g_use_my_apu_code=true.
  //     Under real SPC, snes_readBBus / RtlApuWrite route port I/O
  //     straight to the real APU (no g_is_uploading_apu flag), so
  //     the recompiled upload body runs unmodified.
  //   - $817e: NMI APUIO2 readback bridge.
  //
  // Editorial fixes for original-SMW bugs (uninited regs, OOB reads,
  // etc.) were removed: a faithful recompilation should reproduce the
  // ROM's behavior, not silently mask its bugs. If removal exposes
  // visible regressions, the right fix is in the recompiler/runtime,
  // not in resurrecting smw-rev's editorial patches.
  if (FixBugHook(0x1C641)) {
    // PowerUpAndItemGFXRt_DrawCoinSprite — preserve DB across HLE boundary
    preserved_db = g_cpu->db;
    g_cpu->db = 1;
  } else if (FixBugHook(0x1C644)) {
    g_cpu->db = preserved_db;
  } else if (FixBugHook(0x9A74)) {
    // HLE replacement for CheckWhichControllersArePluggedIn
    CheckWhichControllersArePluggedIn();
    return 0x9A8A;
  } else if (FixBugHook(0x811D)) {
    if (g_use_my_apu_code)
      return 0x8125;
  } else if (FixBugHook(0x80F7)) {
    if (g_use_my_apu_code)
      return 0x80fc;
  } else if (FixBugHook(0x817e)) {
    g_cpu->y = g_ram[kSmwRam_APUI02];
    return 0x8181;
  }
  return 0;
}

void SmwCpuInitialize(void) {
  if (g_rom) {
    *SnesRomPtr(0x843B) = 0x60; // remove WaitForHBlank_Entry2
    *SnesRomPtr(0x2DDA2) = 5;
    *SnesRomPtr(0xCA5AC) = 7;

    uint8 *music = SnesRomPtr(0x8052);
    g_custom_music = music[1] != 0xE8;
    if (g_custom_music) {
      music[0] = 0xea;
      music[1] = 0xea;
      music[2] = 0xea;

      *SnesRomPtr(0x8079) = 0x60;  // HandleSPCUploads_SPC700UploadLoop ret 

      uint8* p = SnesRomPtr(0x8075);
      p[0] = 0x64;
      p[1] = 0x10;
      p[2] = 0x80;
      p[3] = 0xF2;

      printf("Custom music not supported!\n");

      static const uint8 kRevertProcessNormalSprites[] = { 0xda, 0x8a, 0xae, 0x92, 0x16, 0x18, 0x7f, 0xb4, 0xf0, 0x07, 0xaa, 0xbf, 0x00, 0xf0, 0x07, 0xfa, 0x9d, 0xea, 0x15 };
      memcpy(SnesRomPtr(0x180d2), kRevertProcessNormalSprites, sizeof(kRevertProcessNormalSprites));
      static const uint8 kRevertStatusBar[] = { 0xad, 0x22, 0x14, 0xc9 };
      memcpy(SnesRomPtr(0x8FD8), kRevertStatusBar, sizeof(kRevertStatusBar));
      
      if (HAS_HACK(kHack_Walljump)) {
        uint8 *wallhack = SnesRomPtr(0xa2a1);
        wallhack[3] &= 0x7f;
        wallhack = SnesRomPtr(get_24(0xa2a2));
        wallhack[3] &= 0x7f;
      }

      // Reznor platform fix
      static const uint8 kRevert_0x39890[] = { 0xee, 0x0f, 0x14 };
      memcpy(SnesRomPtr(0x39890), kRevert_0x39890, sizeof(kRevert_0x39890));

      static const uint8 kRevert_0x2907a[] = { 0xbd, 0x9d, 0x16, 0xd0 };
      memcpy(SnesRomPtr(0x2907a), kRevert_0x2907a, sizeof(kRevert_0x2907a));
      static const uint8 kRevert_0xf5f3[] = { 0xa0, 0x04, 0x8c, 0xf9, 0x1d };
      memcpy(SnesRomPtr(0xf5f3), kRevert_0xf5f3, sizeof(kRevert_0xf5f3));
      static const uint8 kRevert_0x1bb33[] = { 0xa9, 0x30, 0x9d, 0xea, 0x15 };
      memcpy(SnesRomPtr(0x1bb33), kRevert_0x1bb33, sizeof(kRevert_0x1bb33));
      static const uint8 kRevert_0x2a129[] = { 0xa9, 0x21, 0x95, 0x9e, 0xa9, 0x08, 0x9d, 0xc8, 0x14, 0x22, 0xd2, 0xf7, 0x07 };
      memcpy(SnesRomPtr(0x2a129), kRevert_0x2a129, sizeof(kRevert_0x2a129));
      static const uint8 kRevert_0x2db82[] = { 0xbd, 0xe0, 0x14, 0x99, 0xe0, 0x14 };
      memcpy(SnesRomPtr(0x2db82), kRevert_0x2db82, sizeof(kRevert_0x2db82));
      static const uint8 kRevert_0x2e6ec[] = { 0xa9, 0x38, 0x9d, 0xea, 0x15 };
      memcpy(SnesRomPtr(0x2e6ec), kRevert_0x2e6ec, sizeof(kRevert_0x2e6ec));
    }

    // fast rom
    static const uint8 kRevert_0xfffc[] = { 0x00, 0x80 };
    memcpy(SnesRomPtr(0xfffc), kRevert_0xfffc, sizeof(kRevert_0xfffc));
    static const uint8 kRevert_0xffea[] = { 0x6a, 0x81 };
    memcpy(SnesRomPtr(0xffea), kRevert_0xffea, sizeof(kRevert_0xffea));
    static const uint8 kRevert_0x801c[] = { 0xfb };
    memcpy(SnesRomPtr(0x801c), kRevert_0x801c, sizeof(kRevert_0x801c));
    static const uint8 kRevert_0x8713[] = { 0xb7, 0x02, 0x85, 0x01 };
    memcpy(SnesRomPtr(0x8713), kRevert_0x8713, sizeof(kRevert_0x8713));

  }
}

static void SmwFixSnapshotForCompare(Snapshot *b, Snapshot *a) {
  memcpy(&b->ram[0x0], &a->ram[0x0], 16); // temps
  memcpy(&b->ram[0x10b], &a->ram[0x10b], 0x100 - 0xb);  // stack

  memcpy(&b->ram[0x17bb], &a->ram[0x17bb], 1); // unusedram_7e17bb

  memcpy(&b->ram[0x65], &a->ram[0x65], 12);  // temp66, etc
  memcpy(&b->ram[0x8a], &a->ram[0x8a], 6);  // temp8a, etc

  memcpy(&b->ram[0x14B0], &a->ram[0x14B0], 0x11);  // temp14b0 etc

  memcpy(&b->ram[0x1436], &a->ram[0x1436], 4);  // temp14b0 etc

  memcpy(&b->ram[0x1C00B], &a->ram[0x1C00B], 1);  // lm_varB

  if (g_custom_music) {
    memcpy(&b->ram[0x1DF9], &a->ram[0x1DF9], 8); // sound io
  }

}

static uint32 RunCpuUntilPC(uint32 pc1, uint32 pc2) {
  uint32 addr_last = g_snes->cpu->k << 16 | g_snes->cpu->pc;

  for(;;) {
    snes_runCpu(g_snes);
//    snes_runCycle(g_snes);
    uint32 addr = (g_snes->cpu->k << 16 | g_snes->cpu->pc) & 0x7fffff;
    if (addr != addr_last && (addr == pc1 || addr == pc2)) {
      return addr;
    }
    addr_last = addr;
  }
}

void SmwRunOneFrameOfGame_Emulated(void) {
  Snes *snes = g_snes;
  snes->vPos = snes->hPos = 0;
  snes->cpu->nmiWanted = snes->cpu->irqWanted = false;
  snes->inVblank = snes->inNmi = false;

  // Execute until: mov.b   A, waiting_for_vblank
  RunCpuUntilPC(0x8077, 0x8077);

  g_snes->debug_cycles = 0; // turn off debuig prints if enabled

  // Trigger nmi
  snes->cpu->nmiWanted = true;
  RunCpuUntilPC(0x82C3, 0x83B9);
  snes_runCpu(snes);

  // Right after NMI completes, draw the frame, possibly triggering IRQ.
  assert(!snes->cpu->i);

/*
  snes->vPos = snes->hPos = 0;
  snes->cpu->nmiWanted = snes->cpu->irqWanted = false;
  snes->inVblank = snes->inNmi = false;

  while (!snes->inNmi) {
    snes_handle_pos_stuff(snes);

    if (snes->cpu->irqWanted) {
      RunCpuUntilPC(0x82C3, 0x83B9);
      snes_runCpu(snes);
    }
  }
  */
}


const RtlGameInfo kSmwGameInfo = {
  "smw",
  kGameID_SMW,
  kPatchedCarrys_SMW, arraysize(kPatchedCarrys_SMW),
  &PatchBugs_SMW1,
  &SmwCpuInitialize,
  &SmwRunOneFrameOfGame,
  &SmwRunOneFrameOfGame_Emulated,
  &SmwDrawPpuFrame,
  &SmwFixSnapshotForCompare,
};
