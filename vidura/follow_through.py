"""Follow-through tracking: accepted suggestions earn adopted/lapsed
verdicts by comparing session signal rates before vs. after acceptance.

An accepted fix that actually changed behavior (post-accept sessions
show the mapped metric roughly halved or better) is marked 'adopted' —
a one-time celebration. An accepted fix that sat for 2+ weeks with no
measurable change is marked 'lapsed'. Both are terminal states blocked
from re-suggestion (store.blocked_fix_ids already includes them).
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from vidura.store import set_status

FIX_METRICS: dict[str, str] = {
    "judge-executor-split": "streaks",
    "repeated-error-loop": "errors",
    "single-long-session-no-checkpoints": "long",
}

MIN_BEFORE = 3
MIN_AFTER = 5
ADOPTED_FACTOR = 0.5
LAPSE_DAYS = 14
LONG_SESSION_SECONDS = 7200


def _metric_values(rows: list[sqlite3.Row], metric: str) -> list[float]:
    if metric == "long":
        return [
            1.0 if r["duration_seconds"] and r["duration_seconds"] > LONG_SESSION_SECONDS else 0.0
            for r in rows
        ]
    return [float(r[metric]) for r in rows]


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
