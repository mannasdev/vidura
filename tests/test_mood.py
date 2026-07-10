"""Tests for the mood engine (vidura/mood.py): a pure, deterministic
function over existing store data — no model calls, no new tables.
Priority order (first match wins): STIRRING, PROUD, CONCERNED,
CONTENT, ASLEEP.
"""

from datetime import datetime, timedelta, timezone

from vidura.mood import compute_mood
from vidura.store import (
    _now,
    mark_celebrated,
    open_db,
    record_suggestion,
    set_status,
)
from tests.test_store import _sugg

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _insert_session(conn, path, mtime, streaks):
    conn.execute(
        "INSERT INTO sessions(path, mtime, size, reflected_at, streaks, errors, duration_seconds) "
        "VALUES (?, ?, 0, ?, ?, NULL, NULL)",
        (path, mtime, _now(), streaks),
    )
    conn.commit()


def _iso_days_ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _epoch_days_ago(days: float) -> float:
    return (NOW - timedelta(days=days)).timestamp()


def test_empty_db_is_asleep(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    result = compute_mood(conn, now=NOW)
    assert result["mood"] == "ASLEEP"
    assert result["pending_count"] == 0
    assert result["adopted_uncelebrated_ids"] == []
    assert result["streak_rate_7d"] is None
    assert result["streak_rate_baseline"] is None
    assert result["sessions_24h"] == 0
    conn.close()


def test_pending_suggestion_is_stirring(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    result = compute_mood(conn, now=NOW)
    assert result["mood"] == "STIRRING"
    assert result["pending_count"] == 1
    conn.close()


def test_recent_adopted_uncelebrated_is_proud(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row_id = conn.execute("SELECT id FROM suggestions").fetchone()["id"]
    set_status(conn, row_id, "adopted")
    result = compute_mood(conn, now=NOW)
    assert result["mood"] == "PROUD"
    assert result["adopted_uncelebrated_ids"] == [row_id]
    conn.close()


def test_adopted_older_than_7_days_is_not_proud(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row_id = conn.execute("SELECT id FROM suggestions").fetchone()["id"]
    set_status(conn, row_id, "adopted")
    old = _iso_days_ago(8)
    conn.execute("UPDATE suggestions SET updated_at = ? WHERE id = ?", (old, row_id))
    conn.commit()
    result = compute_mood(conn, now=NOW)
    assert result["mood"] != "PROUD"
    assert result["adopted_uncelebrated_ids"] == []
    conn.close()


def test_celebrated_adopted_is_not_proud(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row_id = conn.execute("SELECT id FROM suggestions").fetchone()["id"]
    set_status(conn, row_id, "adopted")
    mark_celebrated(conn, row_id)
    result = compute_mood(conn, now=NOW)
    assert result["mood"] != "PROUD"
    assert result["adopted_uncelebrated_ids"] == []
    conn.close()


def test_pending_and_adopted_stirring_wins_priority(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="a"))
    record_suggestion(conn, _sugg(fix_id="b"))
    ids = [r["id"] for r in conn.execute("SELECT id FROM suggestions ORDER BY id")]
    set_status(conn, ids[0], "adopted")  # ids[1] remains pending
    result = compute_mood(conn, now=NOW)
    assert result["mood"] == "STIRRING"
    assert result["pending_count"] == 1
    assert result["adopted_uncelebrated_ids"] == [ids[0]]
    conn.close()


def test_concerned_when_recent_streaks_exceed_1_5x_baseline(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # 3 sessions in last 7 days, mean streaks = 3.0
    for i, streaks in enumerate([3, 3, 3]):
        _insert_session(conn, f"recent-{i}", _epoch_days_ago(1 + i), streaks)
    # 3 sessions in prior 21 days (8-28 days ago), mean streaks = 2.0
    for i, streaks in enumerate([2, 2, 2]):
        _insert_session(conn, f"baseline-{i}", _epoch_days_ago(10 + i), streaks)
    result = compute_mood(conn, now=NOW)
    assert result["streak_rate_7d"] == 3.0
    assert result["streak_rate_baseline"] == 2.0
    assert result["mood"] == "CONCERNED"
    conn.close()


def test_concerned_boundary_exactly_1_5x_fires(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    for i, streaks in enumerate([3, 3, 3]):
        _insert_session(conn, f"recent-{i}", _epoch_days_ago(1 + i), streaks)
    for i, streaks in enumerate([2, 2, 2]):
        _insert_session(conn, f"baseline-{i}", _epoch_days_ago(10 + i), streaks)
    result = compute_mood(conn, now=NOW)
    assert result["streak_rate_7d"] == 3.0
    assert result["streak_rate_baseline"] == 2.0
    assert 3.0 >= 1.5 * 2.0
    assert result["mood"] == "CONCERNED"
    conn.close()


def test_not_concerned_below_threshold(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    for i, streaks in enumerate([2, 2, 2]):
        _insert_session(conn, f"recent-{i}", _epoch_days_ago(1 + i), streaks)
    for i, streaks in enumerate([2, 2, 2]):
        _insert_session(conn, f"baseline-{i}", _epoch_days_ago(10 + i), streaks)
    result = compute_mood(conn, now=NOW)
    assert result["mood"] != "CONCERNED"
    conn.close()


def test_insufficient_sessions_in_either_window_is_not_concerned(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    # only 2 sessions in recent window (needs >= 3)
    for i, streaks in enumerate([10, 10]):
        _insert_session(conn, f"recent-{i}", _epoch_days_ago(1 + i), streaks)
    for i, streaks in enumerate([1, 1, 1]):
        _insert_session(conn, f"baseline-{i}", _epoch_days_ago(10 + i), streaks)
    result = compute_mood(conn, now=NOW)
    assert result["mood"] != "CONCERNED"
    assert result["streak_rate_7d"] is None
    conn.close()


def test_content_when_recent_session_and_nothing_else_fired(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _insert_session(conn, "s1", _epoch_days_ago(0.1), 1)
    result = compute_mood(conn, now=NOW)
    assert result["mood"] == "CONTENT"
    assert result["sessions_24h"] == 1
    conn.close()


def test_asleep_when_no_recent_session(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    _insert_session(conn, "s1", _epoch_days_ago(2), 1)
    result = compute_mood(conn, now=NOW)
    assert result["mood"] == "ASLEEP"
    assert result["sessions_24h"] == 0
    conn.close()


def test_all_keys_always_present(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    result = compute_mood(conn, now=NOW)
    expected_keys = {
        "mood",
        "pending_count",
        "adopted_uncelebrated_ids",
        "streak_rate_7d",
        "streak_rate_baseline",
        "sessions_24h",
    }
    assert set(result.keys()) == expected_keys
    conn.close()


def test_now_defaults_to_current_time_when_not_injected(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    result = compute_mood(conn)  # no now= passed
    assert result["mood"] == "ASLEEP"
    conn.close()
