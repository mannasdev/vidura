# Vidura

A local, open-source counselor that reads your Claude Code session logs
and tells you the truth about your friction patterns — rarely, bluntly,
with evidence. Headed toward a menu-bar companion that can act on its
own advice, and a read-only memory API your other agents can draw on.

> Published on PyPI as **`vidura-cli`** (the `vidura` package name belongs
> to an unrelated agent orchestrator). The importable module and all
> commands are still `vidura` / `vidura-*`.

## Status

CLI-complete (M0 + sweep + ledger). `vidura-report` runs one reflection
pass; `vidura-sweep` covers your whole 30-day window in batches and
persists results to a ledger with accept/dismiss feedback. Everything is
local except the reflection call itself, which by default goes through
your own Claude Code CLI (`claude -p`, sandboxed: no tools, one turn).
The transcripts being judged are conversations you already had with
Claude, and they pass a redaction gate first regardless. Prefer fully
local? `VIDURA_REFLECTOR_BACKEND=ollama` uses a local model instead —
judgment quality is noticeably lower (we measured).

No menubar app yet — that's M3 (see Roadmap).

## Requirements

- Python 3.11+
- [Claude Code](https://claude.com/claude-code) installed and authenticated
  (the default reflector backend) — **or** [Ollama](https://ollama.com)
  with a model pulled for the pure-local fallback

## Roadmap

- **M1-full** — embed session chunks into a local vector index so the
  reflector can retrieve "similar past friction" across your whole
  history, not just the current window.
- **M2** — background watcher: reflect automatically at session close.
- **M3** — the menu-bar companion: a small pet that sleeps until it has
  earned counsel, and can *act* on an accepted suggestion (install the
  skill, apply the workflow) with explicit per-action confirmation.
- **M4+** — a read-only MCP memory API over the same database, so your
  other agents can start sessions with cross-session context
  (`search_sessions`, `get_context`). Read-only is a hard rule: agents
  consume memory, only Vidura writes it.

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

Swept sessions also feed a persistent chunk memory (SQLite FTS5): each
new reflection retrieves "similar past friction" from your history and
shows it to the reflector, so recurring patterns get recognized across
weeks, not just within one report. And accepted suggestions are tracked
for follow-through — if the targeted friction actually drops, the ledger
upgrades them to `adopted`; if two weeks pass unchanged, `lapsed`.

State lives in `~/Library/Application Support/Vidura/vidura.db`
(override with `VIDURA_DB_PATH`; delete the folder to erase everything).
Sessions already reflected are skipped on the next run, so the first
sweep is the expensive one and incremental runs cost pennies. An
interrupted sweep (session limit, ctrl-C) resumes where it left off —
sessions are only marked seen when their batch succeeds.

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
Question #3) or the judgment-model floor (design doc Open Question #1 —
try a larger local model or the Anthropic API path) before touching the
prompt again.
