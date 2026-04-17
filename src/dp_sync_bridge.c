/*
 * dp_sync_bridge.c — Oracle bridge: sync functions and type wrappers
 *
 * ╔══════════════════════════════════════════════════════════════════════╗
 * ║  THIS FILE EXISTS SOLELY TO BRIDGE RECOMPILED CODE WITH ORACLE CODE ║
 * ║                                                                      ║
 * ║  Two categories of bridges:                                          ║
 * ║                                                                      ║
 * ║  1. dp_sync: The oracle introduced C pointer variables that the      ║
 * ║     recompiler's raw g_ram[] writes don't update.                    ║
 * ║                                                                      ║
 * ║  2. Struct return wrappers: The oracle wrapped 65816 register        ║
 * ║     returns in C structs for readability. The recompiler needs       ║
 * ║     plain uint8 returns. These wrappers call the oracle function     ║
 * ║     and extract the relevant field.                                  ║
 * ║                                                                      ║
 * ║  REMOVAL CRITERIA (success condition for final decoupled recompiler):║
 * ║  When ALL banks are recompiled and no oracle code remains, this      ║
 * ║  entire bridge file can be deleted. Remove the corresponding         ║
 * ║  name/sig overrides from all .cfg files at the same time.            ║
 * ╚══════════════════════════════════════════════════════════════════════╝
 */

#include "common_rtl.h"
#include "variables.h"

/* Declared in smw_rtl.c — oracle pointer into g_ram for map16 tile data */
extern uint8 *ptr_lo_map16_data;
extern uint8 *ptr_lo_map16_data_bak;

void dp_sync_map16_ptr_to_dp(void) {
#ifdef RECOMP_BANK05
    /* When bank 05 is generated, the generated code writes g_ram[0x6b-0x70]
     * directly from ROM data. The C pointer ptr_lo_map16_data is NOT updated
     * by generated code, so it's stale. Do NOT overwrite the correct g_ram
     * bytes with stale C pointer values. */
    return;
#else
    /*
     * REVERSE sync: C pointer → g_ram.
     * Called at oracle→generated boundary so that generated code's
     * g_ram reads see the correct pointer value set by oracle code.
     */
    uint16 addr = (uint16)(ptr_lo_map16_data - g_ram);
    g_ram[0x6b] = addr & 0xFF;
    g_ram[0x6c] = (addr >> 8) & 0xFF;
    g_ram[0x6d] = 0x7E;  /* Bank $7E — 65816 STA [$6B],Y reads 3-byte ptr from DP $6B */
    g_ram[0x6e] = addr & 0xFF;
    g_ram[0x6f] = (addr >> 8) & 0xFF;
    g_ram[0x70] = 0x7F;  /* Bank $7F — 65816 STA [$6E],Y reads 3-byte ptr from DP $6E */
#endif
}

void dp_sync_map16_ptr(void) {
    /*
     * Reconstruct ptr_lo_map16_data from the raw DP bytes at $6B/$6C.
     * The 65816 code stores a 16-bit WRAM offset at DP $6B (lo) / $6C (hi).
     * The oracle's ptr_lo_map16_data = g_ram + that 16-bit offset.
     *
     * Also sync ptr_lo_map16_data_bak since some functions copy $6B/$6C
     * to $04/$05 and restore later — but the backup pointer is only used
     * by oracle code that reads ptr_lo_map16_data_bak directly.
     */
    uint16 addr = g_ram[0x6b] | (g_ram[0x6c] << 8);
    ptr_lo_map16_data = g_ram + addr;
}

void dp_sync_map16_ptr_bak(void) {
    /* Sync backup pointer from $04/$05 (where PreserveLevelDataPointer stores it) */
    uint16 addr = g_ram[0x04] | (g_ram[0x05] << 8);
    ptr_lo_map16_data_bak = g_ram + addr;
}

/* ═══════════════════════════════════════════════════════════════════════
 * STRUCT RETURN WRAPPERS
 *
 * The oracle's GetDrawInfo returns a GetDrawInfoRes struct (idx, x, y).
 * The 65816 just puts the OAM index in Y and sets carry on failure.
 * The recompiler needs a plain uint8 return (the idx), with 0xFF meaning
 * "offscreen, skip draw". These wrappers call the oracle function and
 * return just .idx.
 *
 * REMOVAL: When GetDrawInfo is itself recompiled (bank $01/$02), it will
 * return uint8 natively and these wrappers become unnecessary.
 * ═══════════════════════════════════════════════════════════════════════ */

#include "funcs.h"

/* ═══════════════════════════════════════════════════════════════════════
 * DEBUG TRACE — temporary, remove after bank01 debugging
 * Traces sprite collision state to find blocks_ypos divergence.
 * ═══════════════════════════════════════════════════════════════════════ */
#include "snes/snes.h"
extern struct Snes *g_snes;
extern int snes_frame_counter;

/* Debug watchpoint: call this after any write to blocks_ypos (g_ram[0x98]).
 * Prints the caller (last recomp func) and the new value. */
extern const char *g_last_recomp_func;

/* Called from _01944D gen code when it writes to g_ram[0xc] */
static int dbg_coll_count = 0;
void debug_trace_01944D(uint8 k, uint8 j) {
    if (snes_frame_counter == 95 && g_snes->runningWhichVersion == 2) {
        fprintf(stderr, "[RECOMP @95] _01944D: k=%d j=%d ypos_lo[k]=0x%02x ypos_hi[k]=0x%02x "
                "ypos_lo[9]=0x%02x rom_offset=0x%02x sum=0x%04x\n",
            k, j, g_ram[0xd8 + k], g_ram[0x14d4 + k],
            g_ram[0xd8 + 9],
            /* Read ROM clipping table at index j */
            ((const uint8*)RomPtr(0x0190f7))[j],
            (uint16)g_ram[0xd8 + k] + ((const uint8*)RomPtr(0x0190f7))[j]);
        fflush(stderr);
    }
}
void debug_watch_blocks_ypos(void) {
    if (snes_frame_counter == 95 && g_snes->runningWhichVersion == 2) {
        uint8 slot = g_ram[0x15e9];
        fprintf(stderr, "[RECOMP @95 #%d] %s: slot=%d "
                "[0x0a]=0x%02x [0x0b]=0x%02x [0x9a]=0x%02x [0x9b]=0x%02x "
                "[0x0c]=0x%02x [0x0d]=0x%02x [0x98]=0x%02x [0x99]=0x%02x\n",
            dbg_coll_count++, g_last_recomp_func, slot,
            g_ram[0xa], g_ram[0xb], g_ram[0x9a], g_ram[0x9b],
            g_ram[0xc], g_ram[0xd], g_ram[0x98], g_ram[0x99]);
        fflush(stderr);
    }
    if (snes_frame_counter > 95) dbg_coll_count = 0;
}

// GetDrawInfo wrappers — now recompiled from ROM in smw_01_gen.c / smw_02_gen.c
// The recompiler handles the PLA/PLA ReturnsTwice pattern natively.
