// gen_stubs.c — Residual functions that are not generated from ROM.
//
// Two categories:
//
//   (A) HandleSPCUploads_Inner — intentional HLE bypass while
//       g_use_my_apu_code=true. Two framework fixes needed for the
//       gen body to work have now landed (SEP #$20 width narrowing in
//       snesrecomp@7dc2cdc; decode-order fall-through repair in
//       snesrecomp@48a11cd). The gen body is now well-formed C; the
//       remaining blocker is at the RUNTIME layer: the HandleSPCUploads
//       entry needs to set g_is_uploading_apu=true so snes_readBBus
//       returns live APU outPorts during the $BBAA handshake poll.
//       Currently that flag is only toggled by FixBugHook($80F7),
//       which fires under the CPU emulator — not from recompiled C.
//       Re-enabling real SPC via recomp therefore requires a new
//       runtime-hook mechanism (recompiler emits an entry/exit hook
//       at specific cfg-tagged addresses, smw_cpu_infra.c provides
//       the Enter/Exit bodies that wrap RtlSetUploadingApu). Until
//       that lands, this stub keeps the HLE SPC path live. To
//       re-enable: add the hook mechanism + directive, revert to
//       'func HandleSPCUploads_Inner 8079 end:80e8 sig:void(*p)'
//       in bank00.cfg, shrink exclude_range 8000 80E8 -> 8000 8079,
//       remove this stub, regen bank 00.
//
//   (B) SmwRunDecompressFromWRAM / _Entry2 — two WRAM-executed
//       functions. Cartridge ROM contains no instructions at bank
//       $7F; the game decompresses code into WRAM at boot and
//       executes it from there. By definition, a recompiler that
//       reads from ROM cannot generate these. They are modelled
//       as HLE and will remain so permanently.

#include "common_rtl.h"
#include "funcs.h"
#include "variables.h"

// (A) HandleSPCUploads_Inner — HLE bypass (see header).
void HandleSPCUploads_Inner(const uint8 *p) { (void)p; }

// (B) SmwRunDecompressFromWRAM ($7F:8000) — clears 128 OAM Y to $F0.
void SmwRunDecompressFromWRAM(void) { ResetSpritesFunc(0); }

// (B) SmwRunDecompressFromWRAM_Entry2 ($7F:812E) — clears sprites 100-127.
void SmwRunDecompressFromWRAM_Entry2(void) { ResetSpritesFunc(100); }
