"""vidura report: the M0 end-to-end entrypoint.

Finds the last DEFAULT_WINDOW_DAYS days of Claude Code session logs,
redacts secrets, extracts friction signals, chunks sessions that show
friction, and runs ONE reflection pass — matching the original spec's
M0 description: "Ingest the last N days of Claude Code JSONL, run one
reflection pass, print a friction report." The window was narrowed from
30 to 14 days after first real use: old friction shouldn't drive
counsel — habits may have improved since.

Only sessions that show a friction signal (a re-prompt streak or a
repeated error) contribute chunks to the payload — this keeps the
payload budget (Task 7) spent on signal, not on every routine session.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vidura.chunk import chunk_turns
from vidura.contract import (
    CONTRACT_VERSION,
    PAYLOAD_BUDGET_CHARS,
    ReflectRequest,
    enforce_payload_budget,
)
from vidura.fix_index import fix_index_for_prompt
from vidura.ingest import parse_session
from vidura.redact import redact
from vidura.reflect import CLAUDE_CLI_CWD_TOKEN, ReflectorError, reflect
from vidura.signals import extract_signals
from vidura.store import blocked_fix_ids, ledger_summary_for_prompt, open_db

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
# 14 days, not 30: old friction shouldn't drive counsel — habits may have
# improved since. --window-days (vidura-sweep) still overrides this.
DEFAULT_WINDOW_DAYS = 14


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


def build_report_request(
    session_paths: list[Path], ledger: list[dict] | None = None
) -> ReflectRequest:
    all_chunks: list[str] = []
    sessions_scanned = 0
    all_reprompt_streaks: list[int] = []
    all_error_repeats: dict[str, int] = {}
    all_tool_error_repeats: dict[str, int] = {}
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
        # tool_error_repeats is judge-visibility only — folded into the
        # signals payload below but deliberately excluded from
        # has_friction (never gates inclusion) same as it's excluded
        # from sweep.py's has_friction and character.py's robot signal.
        for key, count in signals.tool_error_repeats.items():
            all_tool_error_repeats[key] = all_tool_error_repeats.get(key, 0) + count
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
    chunks = enforce_payload_budget(all_chunks, budget_chars=PAYLOAD_BUDGET_CHARS)

    fix_index_dicts = fix_index_for_prompt()

    # Bound the signals payload itself: 30 days of logs can produce
    # hundreds of streaks/error keys, which would silently re-evict the
    # prompt's instructions the same way uncapped chunks did (see the
    # friction-density ranking comment above) — this time inside the
    # signals block rather than the chunks block. Keep the top entries
    # by magnitude (longest streaks, highest-count errors) plus a total
    # count so the model still sees the full scale.
    top_reprompt_streaks = sorted(all_reprompt_streaks, reverse=True)[:50]
    top_error_repeats = dict(
        sorted(all_error_repeats.items(), key=lambda kv: kv[1], reverse=True)[:20]
    )
    # Same top-20 capping as error_repeats, same rationale — judge-
    # visibility only, never fed back into inclusion or character.
    top_tool_error_repeats = dict(
        sorted(all_tool_error_repeats.items(), key=lambda kv: kv[1], reverse=True)[:20]
    )

    return ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={
            "sessions_scanned": sessions_scanned,
            "reprompt_streaks": top_reprompt_streaks,
            "reprompt_streaks_total": len(all_reprompt_streaks),
            "error_repeats": top_error_repeats,
            "tool_error_repeats": top_tool_error_repeats,
            "models_used": sorted(all_models),
        },
        chunks=chunks,
        fix_index=fix_index_dicts,
        ledger=ledger or [],
    )


def print_report(request: ReflectRequest, blocked: set[str] | None = None) -> int:
    try:
        response = reflect(request)
    except ReflectorError as exc:
        print(f"vidura report: degrading to silence: {exc}", file=sys.stderr)
        print("No suggestions this run (reflector unavailable).")
        return 0
    except Exception as exc:
        # Design doc Premise #4: judgment-unavailable must never crash the
        # tool. ReflectorError covers the reflector's own known failure
        # modes, but exceptions can still escape it (e.g. a
        # KeyError from a malformed fix_index entry in reflect()) — any of
        # those must degrade to silence too, not propagate.
        print(f"vidura report: degrading to silence (unexpected error): {exc}", file=sys.stderr)
        print("No suggestions this run (reflector unavailable).")
        return 0

    suggestions = response.suggestions
    if blocked:
        # Belt and braces: the ledger summary already tells the model
        # which fix_ids are dismissed/accepted, but the model can still
        # echo one back — filter it out here so a dismissed suggestion
        # can never resurface in the report (README's "NEVER re-suggested"
        # promise).
        suggestions = [s for s in suggestions if s.fix_id not in blocked]

    if not suggestions:
        print("No suggestions this run — nothing cleared the confidence bar. Silence is correct.")
        return 0

    sessions_scanned = request.signals.get("sessions_scanned", 0)
    print(f"Vidura friction report — {sessions_scanned} sessions scanned\n")
    for suggestion in suggestions:
        print(f"- [{suggestion.fix_id}] confidence={suggestion.confidence:.2f}")
        print(f"  {suggestion.blunt_summary}")
        for quote in suggestion.evidence:
            print(f"    > {quote}")
        print()
    return 0


def main() -> int:
    sessions = find_recent_sessions()
    if not sessions:
        print(f"No Claude Code sessions found in the last {DEFAULT_WINDOW_DAYS} days.")
        return 0
    conn = open_db()
    try:
        ledger = ledger_summary_for_prompt(conn)
        request = build_report_request(sessions, ledger=ledger)
        blocked = blocked_fix_ids(conn)
        return print_report(request, blocked=blocked)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
