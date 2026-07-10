"""The mood engine: a PURE, deterministic function over existing store
data. No model calls, no new data collection — this is the read-model
the future menu-bar pet polls (via vidura-state) to decide how to look.

Six moods exist in the design doc's personality architecture; two are
out of scope here (RECOGNITION needs live session tailing — M3-era;
POKED is a UI interaction, not a stored mood). The remaining four plus
the ASLEEP default are priority-ordered — first match wins:

  1. STIRRING  — a pending suggestion exists (counsel earned, waiting)
  2. PROUD     — a suggestion was adopted in the last 7 days and hasn't
                 been celebrated yet (suggestions.celebrated = 0)
  3. CONCERNED — friction trending above baseline: mean re-prompt
                 streaks/session over the last 7 days >= 1.5x the mean
                 over the prior 21 days, with >= 3 sessions in each
                 window (too few sessions makes the ratio noise, not
                 signal)
  4. CONTENT   — sessions exist in the last 24h and nothing above fired
  5. ASLEEP    — default: no recent activity, nothing pending
"""

import sqlite3
from datetime import datetime, timedelta, timezone

PROUD_WINDOW_DAYS = 7
CONCERNED_RECENT_WINDOW_DAYS = 7
CONCERNED_BASELINE_WINDOW_DAYS = 21
CONCERNED_MIN_SESSIONS = 3
CONCERNED_THRESHOLD = 1.5
CONTENT_WINDOW_HOURS = 24


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_mood(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Return the current mood plus the raw signals that produced it.
    All fields are always present so the CLI/pet never has to guess
    which keys exist for a given mood."""
    now = now or datetime.now(timezone.utc)

    pending_count = conn.execute(
        "SELECT COUNT(*) FROM suggestions WHERE status = 'pending'"
    ).fetchone()[0]

    proud_cutoff = (now - timedelta(days=PROUD_WINDOW_DAYS)).isoformat()
    adopted_rows = conn.execute(
        "SELECT id, updated_at FROM suggestions "
        "WHERE status = 'adopted' AND celebrated = 0 ORDER BY id"
    ).fetchall()
    adopted_uncelebrated_ids = [
        r["id"] for r in adopted_rows if _parse_iso(r["updated_at"]) >= _parse_iso(proud_cutoff)
    ]

    streak_rate_7d = _mean_streaks(
        conn, now - timedelta(days=CONCERNED_RECENT_WINDOW_DAYS), now
    )
    streak_rate_baseline = _mean_streaks(
        conn,
        now - timedelta(days=CONCERNED_BASELINE_WINDOW_DAYS + CONCERNED_RECENT_WINDOW_DAYS),
        now - timedelta(days=CONCERNED_RECENT_WINDOW_DAYS),
    )

    sessions_24h = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE mtime >= ?",
        ((now - timedelta(hours=CONTENT_WINDOW_HOURS)).timestamp(),),
    ).fetchone()[0]

    if pending_count > 0:
        mood = "STIRRING"
    elif adopted_uncelebrated_ids:
        mood = "PROUD"
    elif (
        streak_rate_7d is not None
        and streak_rate_baseline is not None
        and streak_rate_baseline > 0
        and streak_rate_7d >= CONCERNED_THRESHOLD * streak_rate_baseline
    ):
        mood = "CONCERNED"
    elif sessions_24h > 0:
        mood = "CONTENT"
    else:
        mood = "ASLEEP"

    return {
        "mood": mood,
        "pending_count": pending_count,
        "adopted_uncelebrated_ids": adopted_uncelebrated_ids,
        "streak_rate_7d": streak_rate_7d,
        "streak_rate_baseline": streak_rate_baseline,
        "sessions_24h": sessions_24h,
    }


def _mean_streaks(conn: sqlite3.Connection, start: datetime, end: datetime) -> float | None:
    """Mean of sessions.streaks for sessions with mtime in [start, end)
    and a non-NULL streaks value. None if fewer than
    CONCERNED_MIN_SESSIONS such sessions exist in the window — too
    sparse a sample to trust a ratio against."""
    rows = conn.execute(
        "SELECT streaks FROM sessions WHERE mtime >= ? AND mtime < ? AND streaks IS NOT NULL",
        (start.timestamp(), end.timestamp()),
    ).fetchall()
    if len(rows) < CONCERNED_MIN_SESSIONS:
        return None
    values = [r["streaks"] for r in rows]
    return sum(values) / len(values)
