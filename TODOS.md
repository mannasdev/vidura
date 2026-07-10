# TODOS

## Reflector payload token/char budget

**What:** Pick the exact token/char budget number for the `vidura-reflect` stdin payload cap.

**Why:** The JSON contract needs a real, enforced number so an unbounded payload can't silently overflow the reflector model's context window (Eng Review Finding 7, `/plan-eng-review` on the initial design doc).

**Pros:** Turns a silent-degradation risk into an explicit, testable constraint. Any reflector implementation (including future forks) can rely on the documented cap.

**Cons:** Can't be picked correctly until real Claude Code session sizes are measured and the M0 model's actual context window is known — picking a number too early risks guessing wrong in either direction (too tight loses signal, too loose still overflows).

**Context:** Part of the `vidura-reflect` JSON contract spec (design doc Next Steps #3). The contract ships with a documented budget from day one; this TODO is specifically about replacing the placeholder with a measured number once M0's reflector script exists and has run against real logs.

**Depends on:** Next Steps #3 (contract spec drafted) and #4 (M0 reflector script built and run against real logs) from `~/.gstack/projects/vidura/mannas-unknown-design-20260710-033228.md`.

---

## Sandboxing/permission model for third-party reflector forks

**What:** Design a sandboxing or permission model for `vidura-reflect` implementations that aren't the author's own — i.e. community forks, once they exist.

**Why:** Approach C's subprocess boundary makes the reflector swappable by design, and mentions community forks as a possible side-benefit (design doc, Approach C). A swapped-in reflector receives redacted-but-still-sensitive chunk text on stdin with no sandboxing or network restriction — fine while Vidura is single-player (Premise #1, you control both sides of the contract), but a real security question the moment someone else's reflector code runs against your session logs.

**Pros:** Closes a real security gap before OSS release invites forks. Costs nothing to write down now, while the contract is still being designed — much cheaper than retrofitting sandboxing after forks already exist in the wild.

**Cons:** Pure speculative work for v1 — no third party is swapping reflectors yet, and Premise #1 explicitly scopes v1 as single-player. Building this now would be solving a problem that doesn't exist yet.

**Context:** Only becomes load-bearing post-M3 (public v1 release) if a fork ecosystem actually materializes around the `vidura-reflect` contract. Until then, this is a placeholder so the question isn't forgotten.

**Depends on:** M3 shipping and the JSON contract (Next Steps #3) being stable enough that forks are viable in the first place.

---

## Multi-pass (map-reduce) reflection sweep — M0→M1 bridge

**What:** Batch all ~645 sessions into N payload-budget-sized groups, run one claude -p reflection per group, merge suggestions (dedupe by fix_id, keep highest-confidence evidence).

**Why:** M0's conditional pass verdict (2026-07-10): one 48k-char pass covers ~1% of the 30-day window and produced 1 real suggestion; the ≥3 bar failed on coverage, not judgment. 112 true human re-prompt streaks exist in the signals but most never reach the model in a single pass.

**Pros:** Answers the kill criterion's letter with full coverage; the merge step is a natural precursor to M1's ledger semantics (dedupe/never-repeat logic).

**Cons:** ~10-15 claude -p calls per report (cost/time); merge logic is new surface area.

**Depends on:** nothing — buildable immediately on the current reflect/report code.

---

## Execution-mechanism design pass (blocks M3, not M1)

**What:** Decide how the pet executes accepted remedies: (a) run `action.install` commands directly, (b) delegate to `claude -p`, or (c) tiered by `action.kind` — likely (c). Full option analysis in the design doc's "Frontend & Agency Pivot" section.

**Why:** The end goal changed (2026-07-10): the M3 frontend is a menu-bar tamagotchi-style pet that can act on accepted suggestions — a deliberate reversal of the original "Vidura suggests; the human acts" non-goal.

**Non-negotiables (already settled):** per-action explicit confirmation with the exact command shown; executions logged to the ledger; kill switch; no execution for `novel` suggestions until the ledger has feedback history.

**Cons/risks:** An executing fix index is a much larger trust surface than a suggesting one — this interacts with the existing "fork sandboxing" TODO and gets serious the moment community PRs can carry install commands.

**Depends on:** M1 ledger (executions must be logged against suggestions); recommend running this as its own /office-hours or /spec pass before M3 scoping.
