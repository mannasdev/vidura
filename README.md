# Vidura

A local, open-source counselor that reads your Claude Code session logs
and tells you the truth about your friction patterns — rarely, bluntly,
with evidence. Headed toward a menu-bar companion that can act on its
own advice, and a read-only memory API your other agents can draw on.

> Published on PyPI as **`vidura-cli`** (the `vidura` package name belongs
> to an unrelated agent orchestrator). The importable module and all
> commands are still `vidura` / `vidura-*`.

## Install

Two pieces: the **menu-bar app** (the face) and the **core** (the brain).
The app bootstraps the core on first run, so in practice you just install
the app.

**The app.** Download `Vidura.zip` from the
[Releases](https://github.com/mannasdev/vidura/releases) page, unzip it,
and drag `Vidura.app` to `/Applications`.

The app is **not notarized** (this is an unsigned v0), so Gatekeeper will
block the first double-click. To get past it, the *first* time you open it
**right-click (or Control-click) the app → Open → Open** in the dialog.
That clears the quarantine permanently; after that it opens normally. If
right-click → Open doesn't offer an Open button, drop the quarantine flag
by hand:

```bash
xattr -dr com.apple.quarantine /Applications/Vidura.app
```

**The core.** On first run the pet prompts to install the core for you. To
do it yourself:

```bash
pipx install vidura-cli          # preferred (isolated)
pip install --user vidura-cli    # fallback
```

**Build from source.** `make app` produces `pet/dist/Vidura.app`.

## Status

**v1 loop is built** — report, sweep, ledger, optional supermemory,
follow-through (`adopted`/`lapsed`), execution (`vidura-do`), Claude Code
hooks, mood/state CLI, and the menu-bar pet under `pet/`. Everything is
local except the reflection call itself, which goes through your own
Claude Code CLI (`claude -p`, sandboxed: no tools, one turn). Transcripts
pass a redaction gate before anything leaves the process.

**Open gate:** M0 suggestion quality on *your* real last-30-days logs
(see [M0 evaluation](#m0-evaluation-the-actual-gate)). Until that passes,
treat the rest as scaffolding.

## Requirements

- Python 3.11+
- [Claude Code](https://claude.com/claude-code) installed and authenticated
  (the reflector backend)
- macOS 13+ for the menu-bar pet (`pet/`)

## Roadmap

- **Now** — calibrate `PAYLOAD_BUDGET_CHARS` against measured session
  sizes; clear the M0 kill criterion (`vidura-report` → ≥3 non-obvious
  suggestions).
- **M4+** — read-only cross-agent memory via supermemory's own MCP over
  the `vidura` containerTag (Vidura writes only; other agents read).
  Fork-sandboxing for third-party `vidura-reflect` implementations if an
  OSS fork ecosystem appears. See `LATER.md` / `TODOS.md`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
vidura-report
```

## Test

```bash
pytest
```

## Sweep & ledger

`vidura-report` is one reflection pass over a budget-sized slice of your
logs. `vidura-sweep` is the full-coverage version: it packs every
friction session into batches, reflects each one, and merges results
into a persistent ledger.

```bash
vidura-sweep              # top 20 densest batches (the default)
vidura-sweep --full       # every batch — the expensive first run
vidura-ledger             # list suggestions (pending/accepted/dismissed)
vidura-ledger accept 3    # mark suggestion 3 accepted
vidura-ledger dismiss 3   # dismissed suggestions are NEVER re-suggested
```

Swept sessions also feed a persistent chunk memory: each new reflection
retrieves "similar past friction" from your history and shows it to the
reflector (as background context, never quotable evidence), so recurring
patterns get recognized across weeks, not just within one report. And
accepted suggestions are tracked for follow-through — if the targeted
friction actually drops, the ledger upgrades them to `adopted`; if two
weeks pass unchanged, `lapsed`.

### Memory (optional, powered by supermemory)

Chunk memory runs on [supermemory](https://supermemory.ai) — no memory,
or supermemory; there's no local fallback index to reconcile. Without a
key, Vidura runs exactly like M0: `similar_past_friction` is simply
absent, everything else works unchanged.

Two-command quickstart, a local supermemory instance:

```bash
npx supermemory local     # pin a version once you've checked their docs, e.g. npx supermemory@<version> local
```

Then set:

```bash
export SUPERMEMORY_CC_API_KEY=sm_...
# optional, defaults to http://localhost:6767
export VIDURA_SUPERMEMORY_URL=http://localhost:6767
```

**Privacy.** Keep `VIDURA_SUPERMEMORY_URL` on localhost — a non-local URL
is hard-gated off (`VIDURA_SUPERMEMORY_ALLOW_REMOTE=1` is required to
opt in, and even then only one stderr line marks the change). Chunk text
passes the redaction gate before it ever leaves the process, same as
everything the reflector sees. Only a basename (never the full session
path) is stored in supermemory's metadata, scoped under the `vidura`
containerTag.

**Degrade guarantee.** Any supermemory outage, timeout, or the circuit
breaker tripping (first failure, or >30s cumulative wall-time in a
process) disables memory for the rest of that run with at most one
stderr note — the core loop (signals → judge → ledger → pet) never
depends on it.

## Acting on suggestions

Some fixes carry an executable action — Vidura can do the remedy, not
just describe it:

```bash
vidura-ledger accept 6      # decide first — execution is accept-gated
vidura-do 6 --dry-run       # see exactly what would happen
vidura-do 6                 # do it (per-action confirmation, full audit)
```

Actions are risk-tiered: COPY (clipboard, inert), WRITE (append a
declared block to a file you own, full preview), RUN (one fixed command,
shown verbatim, `shell=False`, 300s timeout). Nothing ever runs without
your explicit per-action confirmation; every attempt — including
declines — is audited in the database. `VIDURA_EXECUTION=off` disables
WRITE/RUN entirely.

State lives in `~/Library/Application Support/Vidura/vidura.db`
(override with `VIDURA_DB_PATH`; delete the folder to erase everything).
Sessions already reflected are skipped on the next run, so the first
sweep is the expensive one and incremental runs cost pennies. An
interrupted sweep (session limit, ctrl-C) resumes where it left off —
sessions are only marked seen when their batch succeeds.

### Claude Code hooks (optional)

Vidura can plug into [Claude Code's lifecycle hooks](https://docs.claude.com/en/docs/claude-code/hooks)
so reflection happens event-driven instead of only on a cron tick:

- **SessionEnd** — the moment a Claude Code session ends, spawns a
  detached incremental sweep (`vidura-sweep --batches 3`) in the
  background. Guarded by a 15-minute cooldown and a lockfile so rapid
  session ends can't pile up sweeps, and returns in milliseconds — it
  never blocks Claude Code's shutdown.
- **SessionStart** — if you have pending suggestions, prints one line
  (`Vidura: N suggestion(s) pending — ...`) and nothing otherwise.

```bash
vidura-hook install     # merge both hooks into ~/.claude/settings.json
vidura-hook status      # check what's installed
vidura-hook uninstall   # remove just Vidura's entries, leave others intact
```

`install` is idempotent and backs up your existing `settings.json` first.
Privacy note: per Claude Code's hook contract, whatever the SessionStart
hook prints to stdout is added to that session's context — so the one-line
pending-suggestions nudge becomes something Claude itself can see.

## The pet (menu-bar companion)

Vidura's face: a small menu-bar presence that sleeps almost always —
the rare moment it stirs IS the notification.

```bash
cd pet && swift build -c release
.build/release/ViduraPet &
```

Moods (all computed locally by `vidura-state`, no model calls): asleep,
content, **stirring** (counsel earned — one native notification, never
repeated), proud (a suggestion you accepted measurably changed your
behavior), concerned (friction trending above your own baseline). Click
it: pending suggestions with evidence, Accept / Dismiss / **Do** — Do
shows the exact dry-run preview and only enables Confirm when the
preview succeeded. If the CLIs aren't on PATH, set `VIDURA_BIN` to your
`.venv/bin`. Every 30 minutes it runs an incremental sweep in the
background.

No idle animation, no sound, nothing faster than a 60-second poll —
restraint is the personality.

## M0 evaluation (the actual gate)

This is not a unit test — it's the design doc's kill criterion. Run:

```bash
vidura-report
```

against your real last-30-days Claude Code logs. Read the output.

**Pass:** the report surfaces ≥3 suggestions you judge genuinely
non-obvious — specifically, it should catch something like the
judge/executor split miss described in the project's design doc.

**Fail:** after 2-3 rounds of prompt iteration in `vidura/reflect.py`'s
`SYSTEM_PROMPT`, it still doesn't clear that bar. Per the design doc's
kill criterion: **stop here.** Do not proceed to M1 (SQLite, the
Watcher, the Swift shell). Diagnose whether the blocker is chunking
granularity (`vidura/chunk.py`'s `CHUNK_TARGET_CHARS`, design doc Open
Question #3) or the model floor (design doc Open Question #1) before
touching the prompt again.
