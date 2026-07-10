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

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vidura.chunk import chunk_turns
from vidura.contract import CONTRACT_VERSION, ReflectRequest, enforce_payload_budget
from vidura.fix_index import load_fix_index
from vidura.ingest import parse_session
from vidura.redact import redact
from vidura.reflect import ReflectorError, reflect
from vidura.signals import extract_signals

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_WINDOW_DAYS = 30


def find_recent_sessions(
    root: Path = CLAUDE_PROJECTS_DIR, window_days: int = DEFAULT_WINDOW_DAYS
) -> list[Path]:
    if not root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    sessions = []
    for path in root.rglob("*.jsonl"):
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

    chunks = enforce_payload_budget(all_chunks)

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


def print_report(request: ReflectRequest) -> int:
    try:
        response = reflect(request)
    except ReflectorError as exc:
        print(f"vidura report: degrading to silence: {exc}", file=sys.stderr)
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
    sessions = find_recent_sessions()
    if not sessions:
        print("No Claude Code sessions found in the last 30 days.")
        return 0
    request = build_report_request(sessions)
    return print_report(request)


if __name__ == "__main__":
    sys.exit(main())
