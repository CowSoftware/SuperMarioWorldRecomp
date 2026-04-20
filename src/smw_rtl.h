#ifndef SMW_SMW_RTL_H_
#define SMW_SMW_RTL_H_
#include "common_rtl.h"
#include "common_cpu_infra.h"
#include "snes/snes_regs.h"

enum {
  kSmwRam_APUI02 = 0x18c5,
  kSmwRam_my_flags = 0x19C7C,
};

extern bool g_smw_playback_mode;

// RtlGameInfo hooks (see snesrecomp/runner/src/common_cpu_infra.h).
void SmwOnFrameInputs(uint32 inputs);
void SmwOnFinishLevel(void);
bool SmwSpecialSaveLoad(int cmd, int slot);

void SmwRunOneFrameOfGame_Internal();
void SmwSavePlaythroughSnapshot();

void SmwDrawPpuFrame(void);
void SmwRunOneFrameOfGame(void);

#endif  // SMW_SMW_RTL_H_