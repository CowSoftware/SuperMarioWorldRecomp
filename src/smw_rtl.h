#ifndef SMW_SMW_RTL_H_
#define SMW_SMW_RTL_H_
#include "common_rtl.h"
#include "common_cpu_infra.h"
#include "snes/snes_regs.h"

extern bool g_smw_playback_mode;

// RtlGameInfo hooks (see snesrecomp/runner/src/common_cpu_infra.h).
void SmwOnFinishLevel(void);
bool SmwSpecialSaveLoad(int cmd, int slot);

void SmwRunOneFrameOfGame_Internal();
void SmwSavePlaythroughSnapshot();

void SmwDrawPpuFrame(void);
void SmwRunOneFrameOfGame(void);

#endif  // SMW_SMW_RTL_H_