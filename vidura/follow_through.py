"""Follow-through tracking: accepted suggestions earn adopted/lapsed
verdicts by comparing session signal rates before vs. after acceptance.

An accepted fix that actually changed behavior (post-accept sessions
show the mapped metric roughly halved or better) is marked 'adopted' —
a one-time celebration. An accepted fix that sat for 2+ weeks with no
measurable change is marked 'lapsed'. Both are terminal states blocked
from re-suggestion (store.blocked_fix_ids already includes them).

"tool-usage" is a second, structurally different metric kind alongside
the original before/after-rate comparison: a fix whose action INSTALLS
a tool (Fix.adoption_tool, e.g. "playwright") can't be judged by a
before/after rate — there's no "streaks" for tool usage before the
tool exists. Instead it's a simple post-acceptance usage count:
adopted once >=MIN_TOOL_USAGE_SESSIONS post-accept sessions show the
tool in use, lapsed if LAPSE_DAYS pass with zero usage. Same clock
semantics as the rate-based verdicts (accepted_at from suggestions.
updated_at, sessions matched by mtime, never reflected_at).
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from vidura.fix_index import load_fix_index
from vidura.store import set_status

FIX_METRICS: dict[str, str] = {
    "judge-executor-split": "streaks",
    "repeated-error-loop": "errors",
    "single-long-session-no-checkpoints": "long",
    "manual-ui-verification": "tool-usage",
    # context7 adoption is visible in tools_used (mcp__context7__* tool
    # names). The CLI (brew) and plugin (COPY) fixes are deliberately
    # absent: they run inside Bash calls or skills, never appearing in
    # tools_used, so any metric for them would be a lie.
    "docs-by-paste": "tool-usage",
}

MIN_BEFORE = 3
MIN_AFTER = 5
ADOPTED_FACTOR = 0.5
LAPSE_DAYS = 14
LONG_SESSION_SECONDS = 7200
MIN_TOOL_USAGE_SESSIONS = 3


def _metric_values(rows: list[sqlite3.Row], metric: str) -> list[float]:
    if metric == "long":
        return [
            1.0 if r["duration_seconds"] and r["duration_seconds"] > LONG_SESSION_SECONDS else 0.0
            for r in rows
        ]
    return [float(r[metric]) for r in rows]


def _adoption_tool_for(fix_id: str) -> str | None:
    for fix in load_fix_index():
        if fix.id == fix_id:
            return fix.adoption_tool
    return None


def _session_used_tool(tools_used_json: str | None, tool: str) -> bool:
    """True if any tools_used key contains `tool` case-insensitively —
    sessions.tools_used stores raw tool_use names verbatim (e.g.
    "mcp__playwright__click"), so a substring match against
    adoption_tool ("playwright") catches every tool under that MCP
    server without the fix index having to enumerate them. NULL/empty
    columns (no tool calls that session, or an old pre-v7 row) count as
    not-used, never as an error."""
    if not tools_used_json:
        return False
    try:
        tools_used = json.loads(tools_used_json)
    except (json.JSONDecodeError, TypeError):
        return False
    tool_lower = tool.lower()
    return any(tool_lower in key.lower() for key in tools_used)


def _evaluate_tool_usage(
    conn: sqlite3.Connection, row: sqlite3.Row, fix_id: str, now: datetime
) -> str | None:
    adoption_tool = _adoption_tool_for(fix_id)
    if adoption_tool is None:
        return None
    accepted_at = datetime.fromisoformat(row["updated_at"])
    accepted_epoch = accepted_at.timestamp()

    after_rows = conn.execute(
        "SELECT tools_used FROM sessions WHERE mtime > ? AND tools_used IS NOT NULL",
        (accepted_epoch,),
    ).fetchall()
    used_sessions = sum(
        1 for r in after_rows if _session_used_tool(r["tools_used"], adoption_tool)
    )

    if used_sessions >= MIN_TOOL_USAGE_SESSIONS:
        return "adopted"
    if (now - accepted_at) >= timedelta(days=LAPSE_DAYS) and used_sessions == 0:
        return "lapsed"
    return None


def evaluate_follow_through(
    conn: sqlite3.Connection, now: datetime | None = None
) -> list[tuple[int, str, str]]:
    now = now or datetime.now(timezone.utc)
    transitions: list[tuple[int, str, str]] = []
    accepted = conn.execute(
        "SELECT id, fix_id, updated_at FROM suggestions WHERE status = 'accepted'"
    ).fetchall()
    for row in accepted:
        fix_id = row["fix_id"]
        metric = FIX_METRICS.get(fix_id)
        if metric is None:
            continue

        if metric == "tool-usage":
            verdict = _evaluate_tool_usage(conn, row, fix_id, now)
            if verdict is not None:
                set_status(conn, row["id"], verdict)
                transitions.append((row["id"], fix_id, verdict))
            continue

        accepted_at = datetime.fromisoformat(row["updated_at"])
        accepted_epoch = accepted_at.timestamp()

        if metric == "long":
            column_not_null = "duration_seconds IS NOT NULL"
        else:
            column_not_null = f"{metric} IS NOT NULL"

        before_rows = conn.execute(
            f"SELECT streaks, errors, duration_seconds FROM sessions "
            f"WHERE mtime < ? AND {column_not_null}",
            (accepted_epoch,),
        ).fetchall()
        after_rows = conn.execute(
            f"SELECT streaks, errors, duration_seconds FROM sessions "
            f"WHERE mtime > ? AND {column_not_null}",
            (accepted_epoch,),
        ).fetchall()

        if len(before_rows) < MIN_BEFORE or len(after_rows) < MIN_AFTER:
            continue

        before_vals = _metric_values(before_rows, metric)
        after_vals = _metric_values(after_rows, metric)
        before_rate = sum(before_vals) / len(before_vals)
        after_rate = sum(after_vals) / len(after_vals)

        verdict = None
        if before_rate > 0 and after_rate <= ADOPTED_FACTOR * before_rate:
            verdict = "adopted"
        elif (now - accepted_at) >= timedelta(days=LAPSE_DAYS) and after_rate >= before_rate:
            verdict = "lapsed"

        if verdict is not None:
            set_status(conn, row["id"], verdict)
            transitions.append((row["id"], fix_id, verdict))

    return transitions
