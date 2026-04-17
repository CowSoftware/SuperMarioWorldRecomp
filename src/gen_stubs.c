// gen_stubs.c — The three residual functions that are not generated from ROM.
//
// After the gen_stubs burndown, this file contains exactly three functions
// across two categories. Every other stub that ever lived here has been
// eliminated: dead ones removed, mid-function entries promoted to
// extra_label directives, runtime helpers folded back into ROM decoding,
// and the lone "returns twice" function (GameMode08_FileSelect) unblocked
// by the recompiler's new JML inline-dispatch support.
//
// The three that remain:
//
//   (A) HandleSPCUploads_Inner — an intentional HLE bypass. The ROM body
//       is fully recompilable; the stub exists because of a *runtime*
//       architecture decision, not a recompiler gap. See the detailed
//       comment above the function below.
//
//   (B) SmwRunDecompressFromWRAM / _Entry2 — two WRAM-executed functions.
//       Cartridge ROM contains no instructions at bank $7F; the game
//       decompresses code into WRAM at boot and executes it from there.
//       By definition, a recompiler that reads from ROM cannot generate
//       these. They are modelled as HLE and will remain so permanently.

#include "common_rtl.h"
#include "funcs.h"
#include "variables.h"

// ============================================================================
// (A) HandleSPCUploads_Inner — intentional HLE bypass
// ============================================================================
//
// Address:     $00:8079 (inside exclude_range 8000 80E8 in bank00.cfg)
// Callers:     HandleSPCUploads_UploadSPCEngine ($80E8),
//              HandleSPCUploads_UploadDataToSPC ($80F7)
// ROM body:    the SPC700 transfer protocol handshake. Polls the APU via
//              CMP $2140 / BNE in a tight loop waiting for the SPC to echo
//              the handshake bytes ($BBAA on entry, sequential bytes during
//              transfer), uses [DP $00],Y to read bytes from a caller-supplied
//              long pointer, writes chunks via STA $2140-$2143, and terminates
//              with STZ $2140-$2143. ~113 bytes of real 65816 code.
//
// Status:  the recompiler can now generate this function correctly. In
//          earlier project state this was a true recompiler gap (LDA/CMP
//          against APU ports $2140-$217F fell through to stale g_ram[]
//          reads, and BVS after ADC #$7F emitted a dead "/* overflow? */ 0"
//          branch). The commit that introduced this documentation block
//          also landed:
//              - ABS/ABS_X ReadReg routing for $2140-$217F (recomp.py
//                _resolve_mem) — APU reads now go through the runtime's
//                snes_readBBus with apu-catchup.
//              - ADC signed-overflow (V flag) tracking for BVS/BVC
//                (recomp.py _emit_adc) — the upload-loop continuation
//                BVS at $80D7 now computes the correct V expression.
//              - JML inline-dispatch support (used by other functions
//                but relevant to the same burndown).
//          We exercised the full pipeline: generated the body, verified
//          the C output decoded cleanly, and confirmed the two Rule20
//          violations in callers collapsed with a sig:void() override
//          (X at entry is dead along all paths — first X-use is TAX at
//          $80BA). The generated code was correct.
//
// Why it's still a stub:
//          Despite the recompiler being ready, running the generated body
//          in this project hangs at boot. Root cause is a runtime
//          architecture choice inherited from smw-rev:
//
//          1. This project uses custom HLE SPC emulation. At startup,
//             main.c creates an SmwSpcPlayer via SmwSpcPlayer_Create()
//             and initializes it directly. The SPC engine/samples are
//             loaded into that HLE player, NOT uploaded through the
//             SNES APU via the $2140-$2143 protocol.
//
//          2. snes_readBBus (snes/snes.c) only catches up the real
//             APU emulator and returns g_snes->apu->outPorts[] when
//             g_is_uploading_apu == true:
//
//                 if (adr < 0x80) {
//                   if (!g_is_uploading_apu)
//                     return 0;
//                   snes->apuCatchupCycles = 32;
//                   snes_catchupApu(snes);
//                   return snes->apu->outPorts[adr & 0x3];
//                 }
//
//             Otherwise reads of $2140-$217F return 0 forever.
//
//          3. g_is_uploading_apu is toggled by FixBugHook handlers
//             bracketing the upload functions (smw_cpu_infra.c, hooks
//             at $80F7, $811D, $80FB). But FixBugHook only fires in
//             INTERPRETER mode — it patches a BRK into the ROM and
//             traps on execution. Recompiled code never traps, so in
//             in recomp mode the hooks never run and g_is_uploading_apu stays
//             false forever.
//
//          4. Therefore, if the recompiled inner loop runs, its very
//             first CMP $2140 sees 0, the handshake ($BBAA) never
//             matches, the loop spins, and WatchdogCheck() eventually
//             kills the process.
//
// How to unblock (for future work — this is the "remove HLE" milestone):
//
//          The fix is a runtime change, not a recompiler or codegen
//          change. Two independent edits would be enough:
//
//          Path A — drop the g_is_uploading_apu gate:
//              In snes_readBBus (snes/snes.c, the `if (adr < 0x80)`
//              branch), unconditionally call snes_catchupApu and return
//              apu->outPorts. Same for the $2140-$2143 write side in
//              RtlApuWrite (common_rtl.c). The flag exists only as a
//              performance optimization to avoid per-read catchup when
//              the HLE path is handling SPC communication; once the
//              generated code is the source of truth, the gate becomes
//              counterproductive.
//
//          Path C — disable HLE SPC:
//              Set g_use_my_apu_code = false.
//              The real cycle-accurate APU emulator in apu.c/spc.c
//              already exists; let the recomp path use
//              it too.
//
//          Applying EITHER path (preferably both) lets the recompiled
//          HandleSPCUploads_Inner body run correctly, at which point
//          this stub can be deleted:
//
//              1. Remove this function.
//              2. In bank00.cfg, shrink `exclude_range 8000 80E8` to
//                 `exclude_range 8000 8079` and replace the
//                 `name 008079 HandleSPCUploads_Inner sig:void(*p)` line
//                 with `func HandleSPCUploads_Inner 8079 end:80e8 sig:void()`.
//                 The sig:void() override is necessary because the
//                 auto-sig detector currently can't prove X is dead at
//                 entry across all paths through the BRA at $808B.
//              3. Regenerate bank 00. The generated body will include
//                 proper ReadRegWord($2140) polling, the ADC #$7F BVS
//                 branch using the signed-overflow V expression, DP
//                 long-pointer reads via IndirPtr(*(LongPtr*)(g_ram+0x0), y),
//                 and WriteReg($2140-$2143) stores/STZ.
//              4. Build and verify the attract demo runs.
//
//          The same runtime change unblocks an entire class of
//          polling-loop code for any future game targeted by this
//          recompiler: APU handshakes, auto-joypad latch progress
//          ($4212), VBlank/HBlank status ($4210/$4211), mul/div
//          completion ($2134-$2137, $2214-$2216), DMA status. All of
//          these patterns expect MMIO reads to advance real hardware
//          state. The HLE runner is a convenience inherited from
//          smw-rev, not a game-agnostic foundation.
//
// Parameter: the *p argument is vestigial. The ROM body does not read
//            X/Y/A/*p at entry — it reads the data pointer from DP
//            $0000-$0002, which the callers set up before JSR. The
//            legacy `const uint8 *p` signature was kept to avoid
//            churning caller-side gen code; when this stub is
//            eventually deleted, the sig becomes `void()`.

void HandleSPCUploads_Inner(const uint8 *p) { (void)p; }

// ============================================================================
// (B) Runtime HLE helpers for WRAM-executed code
// ============================================================================
//
// These two entries execute from WRAM bank $7F. At boot the game copies a
// small routine into WRAM via DecompressTo and then JSLs into it. Cartridge
// ROM contains no instructions at $7F:8000 or $7F:812E, so a ROM-based
// recompiler cannot generate them — this is a hard boundary, not a runtime
// architecture choice. They will remain HLE permanently.

// SmwRunDecompressFromWRAM ($7F:8000) — the WRAM routine clears all 128 OAM
// sprite Y positions to $F0 (offscreen). HLE: call ResetSpritesFunc(0).
void SmwRunDecompressFromWRAM(void) { ResetSpritesFunc(0); }

// SmwRunDecompressFromWRAM_Entry2 ($7F:812E) — second entry point in the same
// WRAM routine. Clears sprites 100-127 only. HLE: call ResetSpritesFunc(100).
void SmwRunDecompressFromWRAM_Entry2(void) { ResetSpritesFunc(100); }
