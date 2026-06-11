// Widescreen game-logic override layer for Super Mario World.
//
// Optional, opt-in extension (see ../README.md). Gated on g_ws_active, which
// the frontend sets from the `Widescreen` config option. With g_ws_active
// false none of this is reached and SMW behaves authentically.
#ifndef SMW_WIDESCREEN_OVERRIDES_H
#define SMW_WIDESCREEN_OVERRIDES_H

#include <stdbool.h>

// Defined in src/main.c. The injected dispatch prologues in src/gen/ and the
// override bodies below both branch on this.
extern bool g_ws_active;

// Half-width of the widescreen border, in SNES pixels per side, mirrored from
// the frontend's g_ws_extra. SMW game-logic overrides use this to widen the
// sprite spawn/cull window so enemies populate the extended view instead of
// popping in at the visible edges. 0 when widescreen is off.
extern int g_ws_extra;

// --- Override implementations (added incrementally as Layer 2 lands) ---
// Each corresponds to a rule in overrides.manifest. Signatures match the
// generated functions they replace: RecompReturn Override_X(CpuState *cpu).

#endif  // SMW_WIDESCREEN_OVERRIDES_H
