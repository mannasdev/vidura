"""vidura report: the M0 end-to-end entrypoint.

Finds the last 30 days of Claude Code session logs, redacts secrets,
extracts friction signals, chunks sessions that show friction, and
runs ONE reflection pass — matching the original spec's M0 description:
"Ingest the last 30 days of Claude Code JSONL, run one reflection pass,
print a friction report."

Only sessions that show a friction signal (a re-prompt streak or a
repeated error) contribute chunks to the payload — this keeps the
payload budget (Task 7) spent on signal, not on every routine session.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vidura.chunk import chunk_turns
from vidura.contract import CONTRACT_VERSION, ReflectRequest, enforce_payload_budget
from vidura.fix_index import load_fix_index
from vidura.ingest import parse_session
from vidura.redact import redact
from vidura.reflect import CLAUDE_CLI_CWD_TOKEN, ReflectorError, reflect
from vidura.signals import extract_signals

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_WINDOW_DAYS = 30

# Larger than the contract's conservative default (24k): the reflector now
# requests a 16384-token context window (reflect.OLLAMA_NUM_CTX), which
# comfortably fits ~48k chars of chunks plus prompt scaffolding.
REPORT_PAYLOAD_BUDGET_CHARS = 48000


def find_recent_sessions(
    root: Path = CLAUDE_PROJECTS_DIR, window_days: int = DEFAULT_WINDOW_DAYS
) -> list[Path]:
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    sessions = []
    for path in root.rglob("*.jsonl"):
        # Vidura's own claude-CLI reflector sessions must never be
        # re-ingested — their transcripts are dense with "[user]" markers
        # and would dominate the friction-density ranking (recursion
        # pollution). See reflect.CLAUDE_CLI_CWD.
        if CLAUDE_CLI_CWD_TOKEN in str(path):
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            sessions.append(path)
    return sessions


def build_report_request(session_paths: list[Path]) -> ReflectRequest:
    all_chunks: list[str] = []
    sessions_scanned = 0
    all_reprompt_streaks: list[int] = []
    all_error_repeats: dict[str, int] = {}
    all_models: set[str] = set()

    for path in session_paths:
        turns = list(parse_session(path))
        if not turns:
            continue
        for turn in turns:
            turn.text = redact(turn.text)

        signals = extract_signals(turns)
        sessions_scanned += 1
        all_reprompt_streaks.extend(signals.reprompt_streaks)
        for key, count in signals.error_repeats.items():
            all_error_repeats[key] = all_error_repeats.get(key, 0) + count
        all_models.update(signals.models_used)

        has_friction = bool(signals.reprompt_streaks) or bool(signals.error_repeats)
        if has_friction:
            all_chunks.extend(c.text for c in chunk_turns(turns))

    # Rank chunks by friction density: the payload budget keeps only a
    # sliver of 30 days of logs, and recency alone starves the reflector
    # of the very transcript the signals point at (observed in M0 round 2:
    # 716 reprompt streaks in signals, none visible in the chunks). Density
    # of user turns is a cheap proxy for re-prompt friction.
    # enforce_payload_budget keeps the TAIL of the list, so sort ascending —
    # the densest chunks land at the end and survive the cut.
    all_chunks.sort(key=lambda text: text.count("[user]"))
    chunks = enforce_payload_budget(all_chunks, budget_chars=REPORT_PAYLOAD_BUDGET_CHARS)

    fix_index_dicts = [
        {
            "id": f.id,
            "title": f.title,
            "friction_patterns": f.friction_patterns,
            "remedy": f.remedy,
            "confidence_floor": f.confidence_floor,
        }
        for f in load_fix_index()
    ]

    return ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={
            "sessions_scanned": sessions_scanned,
            "reprompt_streaks": all_reprompt_streaks,
            "error_repeats": all_error_repeats,
            "models_used": sorted(all_models),
        },
        chunks=chunks,
        fix_index=fix_index_dicts,
        ledger=[],
    )


def print_report(request: ReflectRequest, backend: str = "auto") -> int:
    try:
        response = reflect(request, backend=backend)
    except ReflectorError as exc:
        print(f"vidura report: degrading to silence: {exc}", file=sys.stderr)
        print("No suggestions this run (reflector unavailable).")
        return 0
    except Exception as exc:
        # Design doc Premise #4: judgment-unavailable must never crash the
        # tool. ReflectorError covers the reflector's own known failure
        # modes, but exceptions can still escape it (e.g. a
        # ConnectionResetError from call_ollama's networking, or a
        # KeyError from a malformed fix_index entry in reflect()) — any of
        # those must degrade to silence too, not propagate.
        print(f"vidura report: degrading to silence (unexpected error): {exc}", file=sys.stderr)
        print("No suggestions this run (reflector unavailable).")
        return 0

    if not response.suggestions:
        print("No suggestions this run — nothing cleared the confidence bar. Silence is correct.")
        return 0

    sessions_scanned = request.signals.get("sessions_scanned", 0)
    print(f"Vidura friction report — {sessions_scanned} sessions scanned\n")
    for suggestion in response.suggestions:
        print(f"- [{suggestion.fix_id}] confidence={suggestion.confidence:.2f}")
        print(f"  {suggestion.blunt_summary}")
        for quote in suggestion.evidence:
            print(f"    > {quote}")
        print()
    return 0


def main() -> int:
    backend = os.environ.get("VIDURA_REFLECTOR_BACKEND", "auto")
    sessions = find_recent_sessions()
    if not sessions:
        print("No Claude Code sessions found in the last 30 days.")
        return 0
    request = build_report_request(sessions)
    return print_report(request, backend=backend)


if __name__ == "__main__":
    sys.exit(main())
