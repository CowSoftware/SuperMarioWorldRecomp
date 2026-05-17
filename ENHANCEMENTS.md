# Enhancement candidates — SMW recomp

Open enhancement opportunities discovered during recompiler / cfg
work, but deferred because the underlying analyzer or framework
piece needed first investment exceeds the value of the immediate
fix.

Format: one section per enhancement. Each captures (a) what was
attempted, (b) why it's blocked, (c) what would unblock it,
(d) anything stashed for revival.

---

## Both prior enhancement candidates — CLOSED 2026-05-16

The two open items this file used to track:

1. **Non-leaf exit-(M, X) auto-routing** (was blocked by PHP/PLP
   analyzer gap, 2026-05-13).
2. **Leaf auto-router multi-variant gap** (`FileSelectColorMath` at
   `$00:9D30` shape, hand-annotated 2026-05-14).

Both are now closed by a coordinated set of recompiler-side fixes
landed during the 2026-05-16 session:

- `snesrecomp` `73e3d26` — PHP/PLP-bracketed M/X tracking in the
  decoder. Closes the soundness gap that originally blocked
  non-leaf exit-(M, X) inference (the "Mario dies on slope"
  regression class).
- `snesrecomp` `43266e2` — per-variant non-leaf exit-MX inference
  in `exit_mx_autoroute`. Iterates each cfg func entry × each (m, x)
  variant, builds per-variant exit records (`cfg.exit_mx_at_per_variant`).
- `snesrecomp` `03f6076` — dispatch-terminator JSL recognised as a
  function exit point (covers SMW's `$00:86FA` jump-table dispatch
  helper class).
- `snesrecomp` `808e918` — the order-independent fixpoint fix.
  Re-derives every entry × variant on every pass; commits cfg
  records only at convergence. This was the final piece — without
  it, `FileSelectColorMath` and similar were silently getting
  stale post-call routes committed under default-preserve
  assumption.

After these landed, all three hand-written `exit_mx_at` cfg directives
(`$00:F465`, `$00:F461`, `$00:9D30`) were verified redundant and
deleted in top-level commits `a6aeba0` + `4c40c40`. The autoroute
now owns per-variant exit-(M, X) inference for every cfg-declared
function end-to-end.

**Per-variant override count after fixpoint:** 728 → 979 records,
+251 newly-corrected sites that the prior commit-once iteration
had locked at stale defaults.

**v2 unit tests:** 181/181, including a new regression test
`test_caller_exit_revised_when_callee_exit_known_later` that pins
the order-independence behaviour.

Historical record of the original investigations is in git history
on commits `48d45d6` and earlier; nothing in those write-ups is
load-bearing for present-day debugging now that both classes are
closed.

---

## Open items

None at recompiler-level for the previously-tracked auto-router class.
See `ISSUES.md` for the live open-bug list (DA49 async cpu->x_flag
write being the most prominent latent there, with the
`mx_async_check` runtime tripwire now armed to catch it).
