<!-- HERO IMAGE — capture pending (issue #8 W4): docs/images/pet-hero.png
<img src="https://raw.githubusercontent.com/mannasdev/vidura/main/docs/images/pet-hero.png" alt="Vidura's menu-bar pet showing a pending suggestion" width="560">
-->

# Vidura

A local, open-source counselor that reads your Claude Code session logs
and tells you the truth about your friction patterns — rarely, bluntly,
with evidence. Headed toward a menu-bar companion that can act on its
own advice, and a read-only memory API your other agents can draw on.

> Published on PyPI as **`vidura-cli`** (the `vidura` package name belongs
> to an unrelated agent orchestrator). The importable module and all
> commands are still `vidura` / `vidura-*`.

## Install

The core is a Python package:

```bash
pipx install vidura-cli          # preferred (isolated)
pip install --user vidura-cli    # fallback
```

That gives you every command: `vidura-report`, `vidura-sweep`,
`vidura-ledger`, `vidura-do`, `vidura-state`, `vidura-hook`, and
`vidura-reflect`. Each takes `--help` and `--version`.

**The menu-bar app** (optional, macOS). Download `Vidura.zip` from the
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

The app does not install the core for you. If the core is missing, the
app detects that and shows you the one `pipx` command to run, on a
copy-able card with a Re-check button for once you have.

## First report

```bash
vidura-report
```

One reflection pass over a budget-sized slice of your recent Claude Code
logs. Vidura reads the session files, runs everything through a
redaction gate, makes a single sandboxed `claude -p` call (no tools, one
turn), and prints suggestions with the evidence behind them. Nothing
else leaves your machine. If Claude Code isn't installed, Vidura says
exactly that and points you at
[claude.com/claude-code](https://claude.com/claude-code).

A report is one taste. Full coverage of your history is
[`vidura-sweep`](#sweep--ledger); the first sweep is the expensive one,
and incremental runs after it cost pennies.

## The pet (menu-bar companion)

Vidura's face: a small menu-bar presence that sleeps almost always —
the rare moment it stirs IS the notification. Install it from
[Releases](https://github.com/mannasdev/vidura/releases) (see
[Install](#install)) or build it yourself (see
[Build from source](#build-from-source)).

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

Swept sessions also feed a persistent chunk memory (see
[Memory](#memory-optional-powered-by-supermemory)): each new reflection
retrieves "similar past friction" from your history and shows it to the
reflector (as background context, never quotable evidence), so recurring
patterns get recognized across weeks, not just within one report. And
accepted suggestions are tracked for follow-through — if the targeted
friction actually drops, the ledger upgrades them to `adopted`; if two
weeks pass unchanged, `lapsed`.

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

## Claude Code hooks (optional)

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

## Memory (optional, powered by supermemory)

Chunk memory runs on [supermemory](https://supermemory.ai) — no memory,
or supermemory; there's no local fallback index to reconcile.

**No key (the default).** Without a key, Vidura runs exactly like M0:
`similar_past_friction` is simply absent, everything else works
unchanged. You don't have to touch this section at all.

**Hosted supermemory.** Get a key from
[supermemory.ai](https://supermemory.ai) and set it:

```bash
export SUPERMEMORY_CC_API_KEY=sm_...
```

Know what you're opting into: redacted chunk text then leaves your
machine for supermemory's cloud. Chunk text passes the redaction gate
before it ever leaves the process, same as everything the reflector
sees, and only a basename (never the full session path) is stored in
supermemory's metadata, scoped under the `vidura` containerTag. But it
does leave your machine.

**Self-hosted.** [supermemory is open source](https://github.com/supermemoryai/supermemory)
and can run fully locally. Point Vidura at your instance:

```bash
export VIDURA_SUPERMEMORY_URL=http://localhost:6767   # this is the default
```

Their local-server setup has been a moving target, so follow their repo
for how to stand one up rather than any recipe here.

**Privacy.** Keep `VIDURA_SUPERMEMORY_URL` on localhost — a non-local URL
is hard-gated off (`VIDURA_SUPERMEMORY_ALLOW_REMOTE=1` is required to
opt in, and even then only one stderr line marks the change).

**Degrade guarantee.** Any supermemory outage, timeout, or the circuit
breaker tripping (first failure, or >30s cumulative wall-time in a
process) disables memory for the rest of that run with at most one
stderr note — the core loop (signals → judge → ledger → pet) never
depends on it.

## Requirements

- Python 3.11+
- [Claude Code](https://claude.com/claude-code) installed and authenticated
  (the reflector backend)
- macOS 13+ for the menu-bar pet (`pet/`)

## Build from source

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

`make app` builds the menu-bar pet into `pet/dist/Vidura.app`. To run it
straight from the Swift build instead:

```bash
cd pet && swift build -c release
.build/release/ViduraPet &
```

## Roadmap

- **M4+** — read-only cross-agent memory via supermemory's own MCP over
  the `vidura` containerTag (Vidura writes only; other agents read).
  Fork-sandboxing for third-party `vidura-reflect` implementations if an
  OSS fork ecosystem appears. See `LATER.md` / `TODOS.md`.

## Project status

**v1 loop is built** — report, sweep, ledger, optional supermemory,
follow-through (`adopted`/`lapsed`), execution (`vidura-do`), Claude Code
hooks, mood/state CLI, and the menu-bar pet under `pet/`. Everything is
local except the reflection call itself, which goes through your own
Claude Code CLI (`claude -p`, sandboxed: no tools, one turn). Transcripts
pass a redaction gate before anything leaves the process.

Vidura's suggestion quality is gated on a self-evaluation documented in
[docs/design/m0-evaluation.md](docs/design/m0-evaluation.md).
