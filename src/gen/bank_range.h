#ifndef BANK_RANGE_H
#define BANK_RANGE_H

/* Per-function overrides for recompiler --range bisection. Normally empty.
 * When `recomp.py --range A-B` is used (to bisect which function broke
 * after a regen change), this file is regenerated with RECOMP_<BB>_<name>
 * macros marking the functions that were emitted in this run vs. provided
 * by the hand-written src/smw_<BB>.c side. In a regular full-bank regen,
 * banks.h's `#define RECOMP_BANK<BB>` lines drive everything and this
 * file stays empty. */

#endif
