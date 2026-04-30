// gen_stubs.c — Residual functions that are not generated from ROM.
//
// SmwRunDecompressFromWRAM / _Entry2 — two WRAM-executed functions.
// Cartridge ROM contains no instructions at bank $7F; the game
// decompresses code into WRAM at boot and executes it from there. By
// definition, a recompiler that reads from ROM cannot generate these.
// They are modelled as HLE and will remain so permanently.

#include "common_rtl.h"
#include "cpu_state.h"
#include "funcs.h"
#include "variables.h"

// SmwRunDecompressFromWRAM ($7F:8000) — clears 128 OAM Y to $F0.
//
// v2 (M, X) per-variant ABI: every gen-generated v2 function is named
// <base>_M{m}X{x}. Gen call sites use the variant matching caller's
// (m, x) at the JSL site. Since this is a hand-body HLE stub (not gen)
// we declare all four variants as aliases delegating to the canonical
// implementation. Behaviour is M/X-independent (no register-width-
// sensitive code in ResetSpritesFunc), so a single body suffices.
void SmwRunDecompressFromWRAM(CpuState *cpu) { (void)cpu; ResetSpritesFunc(0); }
void SmwRunDecompressFromWRAM_M0X0(CpuState *cpu) { SmwRunDecompressFromWRAM(cpu); }
void SmwRunDecompressFromWRAM_M0X1(CpuState *cpu) { SmwRunDecompressFromWRAM(cpu); }
void SmwRunDecompressFromWRAM_M1X0(CpuState *cpu) { SmwRunDecompressFromWRAM(cpu); }
void SmwRunDecompressFromWRAM_M1X1(CpuState *cpu) { SmwRunDecompressFromWRAM(cpu); }

// SmwRunDecompressFromWRAM_Entry2 ($7F:812E) — clears sprites 100-127.
void SmwRunDecompressFromWRAM_Entry2(CpuState *cpu) { (void)cpu; ResetSpritesFunc(100); }
void SmwRunDecompressFromWRAM_Entry2_M0X0(CpuState *cpu) { SmwRunDecompressFromWRAM_Entry2(cpu); }
void SmwRunDecompressFromWRAM_Entry2_M0X1(CpuState *cpu) { SmwRunDecompressFromWRAM_Entry2(cpu); }
void SmwRunDecompressFromWRAM_Entry2_M1X0(CpuState *cpu) { SmwRunDecompressFromWRAM_Entry2(cpu); }
void SmwRunDecompressFromWRAM_Entry2_M1X1(CpuState *cpu) { SmwRunDecompressFromWRAM_Entry2(cpu); }
