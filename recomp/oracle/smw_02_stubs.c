// smw_02_stubs.c
// Empty stubs for bank02 ROM addresses that have no oracle equivalent
// and could not be decoded by the recompiler.
// RECOMP_WARN: all stubs below are behavior approximations only.
#include "types.h"

// 02848d: SubHorzPosBnk2 -- horizontal position helper.
// Declared void in generated forward declarations; stub does nothing.
void sub_02848d(uint8 k) { (void)k; }

// 02849f: IsOffScreenBnk2 -- LDA spr_xoffscreen_flag[k] | ORA mem_186c[k], RTS
// Return value not captured at any call site; stub does nothing.
void func_02849f(uint8 k) { (void)k; }

// 02d800: 6x NOP + RTS -- explicitly does nothing.
void sub_02d800(uint8 k) { (void)k; }

// 028bb8: Return028BB8 -- single RTS, does nothing.
void func_028bb8(uint8 k) { (void)k; }
