#ifndef BANKS_H
#define BANKS_H

#include "types.h"

/* SMW-specific aggregate types referenced by the recompiler-emitted
 * declarations in recomp/funcs.h and recompiled bodies in src/gen/.
 * They must be visible before either of those is parsed; banks.h is
 * force-included via the vcxproj ForcedIncludeFiles to satisfy that. */

/* HDMA window-buffer routines (Bank 00 ca61/ca6d/ca88/cc14). Holds
 * the pair of bank-local pointers SMW keeps in $04/$06 while running
 * the iris / keyhole / circle HDMA effects. */
typedef struct HdmaPtrs {
  uint8 *r4;
  uint8 *r6;
} HdmaPtrs;

/* Generic two-byte return — used wherever a recompiled routine needs
 * to return two uint8s. Field names match what recomp.py emits. */
typedef struct PairU8 {
  uint8 first;
  uint8 second;
} PairU8;

/* Overworld horizontal/vertical position bundle — packed scratch
 * registers $00/$02/$06/$08 returned by Bank 04's
 * CheckPlayerToOverworldSpriteColl_SubOverworldHorizAndVertPos. */
typedef struct OwHvPos {
  uint16 r0, r2, r6, r8;
} OwHvPos;

/* Per-game struct types used by sig:Type and (Type*)(g_ram+...) casts
 * the recompiler emits. The recompiled bodies access these regions
 * through absolute g_ram[...] offsets, not through struct fields, so
 * for the framework's purposes these only need to (a) exist as named
 * types and (b) have a size at least covering the DP/WRAM span the
 * recompiler thinks they occupy. Hand-written bodies that need real
 * field access can extend or override these in a per-bank header. */

/* DP $00-$0B — sprite-vs-block collision context. */
typedef struct CollInfo {
  uint8 raw[12];
} CollInfo;

/* DP $0A-$0D — extended collision output. */
typedef struct ExtCollOut {
  uint8 raw[4];
} ExtCollOut;

/* DP $10 + bool fields — platform collision return packet. */
typedef struct CheckPlatformCollRet {
  uint8 raw[8];
} CheckPlatformCollRet;

/* WRAM $14B0..$14BF — tilting-platform circle-coord args, passed by
 * value into Bank 01's CalculateCircleCoordinatesForTiltingPlaform.
 * Size covers the recompiler's expected span; the body reads via
 * absolute g_ram offsets, so the field layout is opaque here. */
typedef struct CalcTiltPlatformArgs {
  uint8 raw[16];
} CalcTiltPlatformArgs;

// ALL BANKS ENABLED — full recomp experiment
#define RECOMP_BANK00
#define RECOMP_BANK01
#define RECOMP_BANK02
#define RECOMP_BANK03
#define RECOMP_BANK04
#define RECOMP_BANK05
#define RECOMP_BANK07
#define RECOMP_BANK0C
#define RECOMP_BANK0D

// Per-function overrides for bisection (normally empty)
#include "gen/bank_range.h"

#endif // BANKS_H
