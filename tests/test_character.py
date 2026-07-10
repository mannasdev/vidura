"""Tests for the character engine (vidura/character.py): the pet's
SPECIES is earned by usage patterns over a rolling 14-day window.
Priority order (first match wins): face, dad, robot, founder,
turtleneck, temple-cat (default).
"""

import json
from datetime import datetime, timedelta, timezone

from vidura.character import (
    MIN_SESSIONS,
    STICKINESS_TENURE_DAYS,
    WINDOW_DAYS,
    assign_character,
    evaluate_character,
)
from vidura.contract import Suggestion
from vidura.store import (
    current_character,
    open_db,
    record_character,
    record_suggestion,
    set_status,
)

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _epoch_days_ago(days: float) -> float:
    return (NOW - timedelta(days=days)).timestamp()


def _iso_days_ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _seed_session(conn, path, days_ago, streaks=0, errors=0, duration=0.0, ref=NOW):
    conn.execute(
        "INSERT INTO sessions(path, mtime, size, reflected_at, streaks, errors, duration_seconds) "
        "VALUES (?, ?, 0, '2026-01-01T00:00:00+00:00', ?, ?, ?)",
        (path, (ref - timedelta(days=days_ago)).timestamp(), streaks, errors, duration),
    )
    conn.commit()


def _seed_sessions(conn, n, days_span=14, ref=NOW, **kwargs):
    """Spread n sessions evenly across the window ending at ref (all
    inside it)."""
    for i in range(n):
        _seed_session(conn, f"/s{i}", days_ago=(i % days_span) + 0.1, ref=ref, **kwargs)


def _sugg(fix_id):
    return Suggestion(fix_id=fix_id, confidence=0.8, evidence=["q"], blunt_summary="s")


def _seed_suggestion_with_status(conn, fix_id, status, days_ago):
    record_suggestion(conn, _sugg(fix_id))
    row = conn.execute("SELECT id FROM suggestions WHERE fix_id = ?", (fix_id,)).fetchone()
    set_status(conn, row["id"], status)
    conn.execute(
        "UPDATE suggestions SET updated_at = ? WHERE id = ?",
        (_iso_days_ago(days_ago), row["id"]),
    )
    conn.commit()
    return row["id"]


# --- rule 1: face (insufficient data) ---


def test_face_when_fewer_than_min_sessions(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS - 1)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "face"
    assert "getting to know you" in result["reason"]
    assert result["metrics"]["n_sessions"] == MIN_SESSIONS - 1
    conn.close()


def test_not_face_at_exactly_min_sessions(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] != "face"
    conn.close()


# --- rule 2: dad ---


def test_dad_when_lapsed_dominates_adopted(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS)
    _seed_suggestion_with_status(conn, "fix-a", "lapsed", days_ago=1)
    _seed_suggestion_with_status(conn, "fix-b", "lapsed", days_ago=2)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "dad"
    assert "accept advice" in result["reason"]
    conn.close()


def test_not_dad_when_lapsed_below_two(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS)
    _seed_suggestion_with_status(conn, "fix-a", "lapsed", days_ago=1)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] != "dad"
    conn.close()


def test_not_dad_when_adopted_matches_lapsed(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS)
    _seed_suggestion_with_status(conn, "fix-a", "lapsed", days_ago=1)
    _seed_suggestion_with_status(conn, "fix-b", "lapsed", days_ago=2)
    _seed_suggestion_with_status(conn, "fix-c", "adopted", days_ago=1)
    _seed_suggestion_with_status(conn, "fix-d", "adopted", days_ago=2)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] != "dad"
    conn.close()


def test_dad_beats_robot(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # robot-qualifying signals AND dad-qualifying suggestion history
    _seed_sessions(conn, MIN_SESSIONS, errors=2, duration=8000)
    _seed_suggestion_with_status(conn, "fix-a", "lapsed", days_ago=1)
    _seed_suggestion_with_status(conn, "fix-b", "lapsed", days_ago=2)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "dad"
    conn.close()


# --- rule 3: robot ---


def test_robot_when_high_errors_and_long_sessions(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS, errors=2, duration=8000)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "robot"
    assert "error loops" in result["reason"]
    conn.close()


def test_not_robot_when_long_session_rate_too_low(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS, errors=2, duration=100)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] != "robot"
    conn.close()


def test_robot_beats_founder(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # founder-qualifying velocity AND robot-qualifying error/long-session signals
    n = 40  # sessions_per_day ~2.86 over 14 days
    for i in range(n):
        _seed_session(conn, f"/s{i}", days_ago=(i % 14) + 0.1, errors=2, duration=8000)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "robot"
    conn.close()


# --- rule 4: founder ---


def test_founder_when_high_velocity_and_hours(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    n = 40  # ~2.86/day
    for i in range(n):
        _seed_session(conn, f"/s{i}", days_ago=(i % 14) + 0.1, duration=4000)  # ~44.4 total hours
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "founder"
    assert "velocity" in result["reason"]
    conn.close()


def test_not_founder_when_total_hours_too_low(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    n = 40
    for i in range(n):
        _seed_session(conn, f"/s{i}", days_ago=(i % 14) + 0.1, duration=10)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] != "founder"
    conn.close()


def test_founder_beats_turtleneck(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # turtleneck-qualifying low streaks AND founder-qualifying velocity/hours
    n = 40
    for i in range(n):
        _seed_session(conn, f"/s{i}", days_ago=(i % 14) + 0.1, streaks=0, duration=4000)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "founder"
    conn.close()


# --- rule 5: turtleneck ---


def test_turtleneck_when_low_streaks_and_low_velocity(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS, streaks=0)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "turtleneck"
    assert "unhurried" in result["reason"]
    conn.close()


def test_not_turtleneck_when_velocity_too_high(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    n = 30  # sessions_per_day = 30/14 ~= 2.14 >= 1.5
    for i in range(n):
        _seed_session(conn, f"/s{i}", days_ago=(i % 14) + 0.1, streaks=0, duration=10)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] != "turtleneck"
    conn.close()


# --- rule 6: temple-cat (default) ---


def test_temple_cat_default(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS, streaks=2, duration=10)
    result = evaluate_character(conn, now=NOW)
    assert result["character"] == "temple-cat"
    assert "balanced" in result["reason"]
    conn.close()


def test_metrics_keys_present(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS)
    result = evaluate_character(conn, now=NOW)
    assert set(result.keys()) == {"character", "reason", "metrics"}
    expected_metrics = {
        "n_sessions",
        "sessions_per_day",
        "total_hours",
        "avg_errors_per_session",
        "long_session_rate",
        "avg_streaks_per_session",
        "lapsed_count",
        "adopted_count",
    }
    assert expected_metrics <= set(result["metrics"].keys())
    conn.close()


def test_now_defaults_to_current_time(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    result = evaluate_character(conn)  # no now= passed
    assert result["character"] == "face"
    conn.close()


# --- assign_character: stickiness + recording ---


def test_first_assignment_always_recorded(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert current_character(conn) is None
    result = assign_character(conn, now=NOW)
    assert result["character"] == "face"
    row = current_character(conn)
    assert row is not None
    assert row["character"] == "face"
    assert row["reason"]
    json.loads(row["metrics"])  # must be valid JSON
    conn.close()


def test_no_new_row_when_character_unchanged(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assign_character(conn, now=NOW)
    assign_character(conn, now=NOW + timedelta(days=1))
    rows = conn.execute("SELECT COUNT(*) c FROM character_history").fetchone()["c"]
    assert rows == 1
    conn.close()


def test_stickiness_blocks_change_before_tenure(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # establish temple-cat as current, with sessions that would qualify
    # as turtleneck if computed fresh
    _seed_sessions(conn, MIN_SESSIONS, streaks=2, duration=10)
    first = assign_character(conn, now=NOW)
    assert first["character"] == "temple-cat"

    # wipe sessions and reseed as turtleneck-qualifying, before tenure elapses
    conn.execute("DELETE FROM sessions")
    conn.commit()
    later = NOW + timedelta(days=STICKINESS_TENURE_DAYS - 1)
    _seed_sessions(conn, MIN_SESSIONS, streaks=0, ref=later)
    result = assign_character(conn, now=later)
    assert result["character"] == "temple-cat"  # stickiness held
    rows = conn.execute("SELECT COUNT(*) c FROM character_history").fetchone()["c"]
    assert rows == 1
    conn.close()


def test_stickiness_allows_change_after_tenure(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS, streaks=2, duration=10)
    assign_character(conn, now=NOW)

    conn.execute("DELETE FROM sessions")
    conn.commit()
    later = NOW + timedelta(days=STICKINESS_TENURE_DAYS)
    _seed_sessions(conn, MIN_SESSIONS, streaks=0, ref=later)
    result = assign_character(conn, now=later)
    assert result["character"] == "turtleneck"
    rows = conn.execute("SELECT COUNT(*) c FROM character_history").fetchone()["c"]
    assert rows == 2
    conn.close()


def test_face_upgrades_immediately_ignoring_stickiness(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # start as face (insufficient data)
    _seed_sessions(conn, MIN_SESSIONS - 1)
    first = assign_character(conn, now=NOW)
    assert first["character"] == "face"

    # immediately (same instant) gain enough sessions to qualify for
    # a real character — the face exception bypasses the 7-day tenure
    conn.execute("DELETE FROM sessions")
    conn.commit()
    _seed_sessions(conn, MIN_SESSIONS, streaks=2, duration=10)
    result = assign_character(conn, now=NOW)
    assert result["character"] == "temple-cat"
    rows = conn.execute("SELECT COUNT(*) c FROM character_history").fetchone()["c"]
    assert rows == 2
    conn.close()


def test_record_character_snapshot_is_metrics_json(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _seed_sessions(conn, MIN_SESSIONS)
    assign_character(conn, now=NOW)
    row = current_character(conn)
    metrics = json.loads(row["metrics"])
    assert "n_sessions" in metrics
    conn.close()
