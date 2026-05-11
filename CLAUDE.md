# SuperMarioWorldRecomp — Project Rules

This project follows the global `recomp-template` rules in
`F:/Projects/recomp-template/NES/PRINCIPLES.md` (the platform is SNES,
but the recomp methodology is identical). Project-specific overrides
and additions live here.

---

# RULE 0 — NEVER PAUSE THE RUNTIME (MANDATORY)

You MUST NOT pause the running game under any circumstance.

Forbidden:
- `pause` TCP command
- `step` / `step_block` / `emu_step` / `break_continue`
- Any flag, hook, or breakpoint that halts execution
- "Pause to take a measurement"
- "Pause both sides to compare state"
- "Step N instructions to capture X"
- "Just one quick pause to grab a screenshot at a known frame"
- Sending a `screenshot` or any other command that has, as a side
  effect, paused the runtime — if you observe a pause, immediately
  send `continue` and investigate which command caused it

There is NO legitimate reason to pause. Every observation goes
through the always-on ring buffers.

If you think you need to pause:
- STOP.
- Identify the ring buffer that already records what you want to see.
- If no ring covers the data you need, EXTEND the ring buffer in
  the runtime; do not pause.
- Query the ring backward in time for the window of interest.

The ring buffers:
- `cpu_trace_ring` (16M entries, ~640 MB): every basic-block entry
  with full CPU state. Query via `trace_get_v2`.
- `block_watch` slots: arm a PC+addresses-of-interest, the runtime
  captures every hit while running, query via `block_watch_get`.
- WRAM-watch slots: always-on byte-write tracking for armed ranges.
- VRAM-write ring: always-on byte-write tracking.
- Frame ring: 36,000 frames of CPU/WRAM snapshots, queryable backward.

These are designed so the game keeps running while you observe.
Pausing defeats the whole observability architecture.

This rule is non-negotiable. Violating it invalidates every
conclusion derived from the paused observation.

---

# OTHER PROJECT RULES

- `src/gen/` and `recomp/funcs.h` are generated. Never hand-edit.
  Fix the recompiler or cfg.
- Match Codex's wrapper-fix pattern when cross-bank `name <pc>
  <body_name>` aliases bypass a PHB/PHK/PLB wrapper at <pc>: declare
  the wrapper as a `func` in bank01.cfg, rename cross-bank `name`
  entries from body name to wrapper name. See commit 9dc3131 for
  the template.
- See `CODEX_ANALYSIS.md` for the canonical write-up of the wrapper
  bypass class.
