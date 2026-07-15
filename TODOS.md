# TODOS

Open work only. Shipped / calibrated items stay out of this file.

## M0 kill criterion (suggestion quality)

**What:** Run `vidura-report` against the author's real last-14-days
Claude Code logs. Pass = ≥3 suggestions judged genuinely non-obvious.
Fail after 2–3 prompt iterations in `vidura/reflect.py`'s
`SYSTEM_PROMPT` = stop per the design doc; diagnose chunking vs model
floor before touching the prompt again.

**Why:** This is the product gate. The loop is coded; it only matters if
the counsel is real.

**Depends on:** Nothing — runnable now.

---

## Sandboxing/permission model for third-party reflector forks

**What:** Design a sandboxing or permission model for `vidura-reflect`
implementations that aren't the author's own.

**Why:** A swapped-in reflector receives redacted-but-still-sensitive
chunk text on stdin with no sandboxing. Fine for single-player v1;
real once OSS invites forks.

**When:** Post-public release, only if a fork ecosystem materializes.
See `LATER.md`.
