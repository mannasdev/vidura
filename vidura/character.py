"""The character engine: a PURE, deterministic function over existing
store data (sessions + suggestions), no model calls. Mood is today's
mirror; character is who you've been for weeks — the pet's SPECIES is
earned by usage patterns over a rolling WINDOW_DAYS window, same
philosophy as suggestions.

Six characters exist, priority-ordered — first match wins. Each rule's
reason string is a full human sentence with the key numbers baked in
(e.g. "The Founder — 41 sessions and 52 hours in 14 days, relentless
velocity"), since that string is what vidura-state surfaces verbatim
as character_reason:

  1. face         — n_sessions < MIN_SESSIONS in window (insufficient
                     data; "still getting to know you")
  2. dad          — lapsed_count >= 2 AND lapsed_count > adopted_count
                     ("you accept advice and don't change")
  3. robot        — avg_errors_per_session >= ROBOT_ERROR_THRESHOLD AND
                     long_session_rate >= ROBOT_LONG_SESSION_RATE
                     ("grinding through error loops")
  4. founder      — sessions_per_day >= FOUNDER_SESSIONS_PER_DAY AND
                     total_hours >= FOUNDER_TOTAL_HOURS ("relentless
                     velocity")
  5. turtleneck   — avg_streaks_per_session <= TURTLENECK_MAX_STREAKS
                     AND sessions_per_day < TURTLENECK_MAX_SESSIONS_PER_DAY
                     ("careful, unhurried craft")
  6. temple-cat   — default ("balanced practice")

STICKINESS: the currently assigned character persists unless tenure
(time since the current assignment's assigned_at) >= STICKINESS_TENURE_DAYS
AND the newly computed character differs from the current one. The one
exception is the face character: it upgrades to anything immediately
once n_sessions >= MIN_SESSIONS, regardless of tenure — the "still
getting to know you" placeholder should never block real data from
landing the moment it's available.

Every assignment (including the very first) is recorded to
character_history with a reason string and a metrics-snapshot JSON, so
the table is a full audit trail, not just a mutable current pointer.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from vidura.store import current_character, record_character

WINDOW_DAYS = 14
MIN_SESSIONS = 15
STICKINESS_TENURE_DAYS = 7

DAD_MIN_LAPSED = 2

ROBOT_ERROR_THRESHOLD = 1.5
ROBOT_LONG_SESSION_RATE = 0.3
LONG_SESSION_SECONDS = 7200

FOUNDER_SESSIONS_PER_DAY = 2.5
FOUNDER_TOTAL_HOURS = 40.0

TURTLENECK_MAX_STREAKS = 1.0
TURTLENECK_MAX_SESSIONS_PER_DAY = 1.5


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _window_sessions(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT streaks, errors, duration_seconds FROM sessions WHERE mtime >= ? AND mtime < ?",
        (start.timestamp(), end.timestamp()),
    ).fetchall()


def _status_change_count(
    conn: sqlite3.Connection, status: str, start: datetime, end: datetime
) -> int:
    """Count suggestions whose status is currently `status` AND whose
    updated_at (the timestamp of that status change, per set_status)
    falls inside [start, end)."""
    rows = conn.execute(
        "SELECT updated_at FROM suggestions WHERE status = ?", (status,)
    ).fetchall()
    return sum(1 for r in rows if start <= _parse_iso(r["updated_at"]) < end)


def evaluate_character(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Compute the character the current usage pattern earns, from
    scratch, with no memory of any prior assignment. Stickiness is
    layered on top by assign_character — this function is the pure
    per-instant verdict."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=WINDOW_DAYS)

    session_rows = _window_sessions(conn, start, now)
    n_sessions = len(session_rows)

    durations = [r["duration_seconds"] for r in session_rows if r["duration_seconds"] is not None]
    errors = [r["errors"] for r in session_rows if r["errors"] is not None]
    streaks = [r["streaks"] for r in session_rows if r["streaks"] is not None]

    total_hours = sum(durations) / 3600.0 if durations else 0.0
    sessions_per_day = n_sessions / WINDOW_DAYS
    avg_errors_per_session = sum(errors) / len(errors) if errors else 0.0
    long_session_rate = (
        sum(1 for d in durations if d > LONG_SESSION_SECONDS) / len(durations) if durations else 0.0
    )
    avg_streaks_per_session = sum(streaks) / len(streaks) if streaks else 0.0

    lapsed_count = _status_change_count(conn, "lapsed", start, now)
    adopted_count = _status_change_count(conn, "adopted", start, now)

    metrics = {
        "n_sessions": n_sessions,
        "sessions_per_day": sessions_per_day,
        "total_hours": total_hours,
        "avg_errors_per_session": avg_errors_per_session,
        "long_session_rate": long_session_rate,
        "avg_streaks_per_session": avg_streaks_per_session,
        "lapsed_count": lapsed_count,
        "adopted_count": adopted_count,
    }

    if n_sessions < MIN_SESSIONS:
        character = "face"
        reason = "The Face — still getting to know you"
    elif lapsed_count >= DAD_MIN_LAPSED and lapsed_count > adopted_count:
        character = "dad"
        reason = (
            f"The Dad — {lapsed_count} lapsed vs. {adopted_count} adopted in "
            f"{WINDOW_DAYS} days, you accept advice and don't change"
        )
    elif avg_errors_per_session >= ROBOT_ERROR_THRESHOLD and long_session_rate >= ROBOT_LONG_SESSION_RATE:
        character = "robot"
        reason = (
            f"The Robot — {avg_errors_per_session:.1f} errors/session and "
            f"{long_session_rate * 100:.0f}% long sessions in {WINDOW_DAYS} days, "
            "grinding through error loops"
        )
    elif sessions_per_day >= FOUNDER_SESSIONS_PER_DAY and total_hours >= FOUNDER_TOTAL_HOURS:
        character = "founder"
        reason = (
            f"The Founder — {n_sessions} sessions and {total_hours:.0f} hours in "
            f"{WINDOW_DAYS} days, relentless velocity"
        )
    elif avg_streaks_per_session <= TURTLENECK_MAX_STREAKS and sessions_per_day < TURTLENECK_MAX_SESSIONS_PER_DAY:
        character = "turtleneck"
        reason = (
            f"The Turtleneck — {avg_streaks_per_session:.1f} streaks/session and "
            f"{sessions_per_day:.1f} sessions/day in {WINDOW_DAYS} days, careful, unhurried craft"
        )
    else:
        character = "temple-cat"
        reason = f"The Temple Cat — {n_sessions} sessions in {WINDOW_DAYS} days, balanced practice"

    return {"character": character, "reason": reason, "metrics": metrics}


def assign_character(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Compute the freshly-earned character and apply stickiness against
    whatever is currently recorded, recording a new character_history
    row ONLY when the visible assignment actually changes (or on the
    very first run, when there is nothing to compare against).

    Returns the dict describing whatever character is now in effect
    (which may be the persisted-via-stickiness old one, not the freshly
    computed one)."""
    now = now or datetime.now(timezone.utc)
    computed = evaluate_character(conn, now=now)
    current = current_character(conn)

    if current is None:
        record_character(
            conn, computed["character"], computed["reason"], json.dumps(computed["metrics"]), assigned_at=now.isoformat()
        )
        return computed

    if computed["character"] == current["character"]:
        return computed

    tenure = now - _parse_iso(current["assigned_at"])
    face_upgrade = current["character"] == "face" and computed["character"] != "face"

    if face_upgrade or tenure >= timedelta(days=STICKINESS_TENURE_DAYS):
        record_character(
            conn, computed["character"], computed["reason"], json.dumps(computed["metrics"]), assigned_at=now.isoformat()
        )
        return computed

    # Stickiness holds: the currently assigned character persists even
    # though a different one would be computed fresh right now.
    return {
        "character": current["character"],
        "reason": current["reason"],
        "metrics": computed["metrics"],
    }
