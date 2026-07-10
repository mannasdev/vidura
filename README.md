# Vidura

A local, open-source counselor that reads your Claude Code session logs
and tells you the truth about your friction patterns — rarely, bluntly,
with evidence.

## Status

Pre-M0. This is the reflector-only build: `vidura report` reads your last
30 days of Claude Code logs, redacts secrets, extracts friction signals,
and asks a local Ollama model whether anything clears the bar for a
suggestion. No menubar app yet — that's M3.

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally with a model pulled (default: `qwen2.5:14b`)

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
