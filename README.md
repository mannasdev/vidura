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
