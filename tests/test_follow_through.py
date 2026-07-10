from datetime import datetime, timedelta, timezone

from vidura.contract import Suggestion
from vidura.follow_through import evaluate_follow_through
from vidura.store import ledger_entries, open_db, record_suggestion, set_status


def _sugg(fix_id="judge-executor-split", confidence=0.8, evidence=None, novel=False):
    return Suggestion(
        fix_id=fix_id,
        confidence=confidence,
        evidence=evidence or ["some quote"],
        blunt_summary="a blunt sentence",
        novel=novel,
    )


def _seed_session(conn, path, mtime, streaks=0, errors=0, duration=0.0):
    conn.execute(
        "INSERT INTO sessions(path, mtime, size, reflected_at, streaks, errors, duration_seconds) "
        "VALUES (?, ?, 0, '2026-01-01T00:00:00+00:00', ?, ?, ?)",
        (path, mtime, streaks, errors, duration),
    )
    conn.commit()


def test_adopted_when_error_rate_halves(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="repeated-error-loop"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(conn, f"/b{i}", accepted_epoch - 1000 - i, errors=4)
    for i in range(5):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i, errors=1)
    transitions = evaluate_follow_through(conn)
    assert transitions == [(row["id"], "repeated-error-loop", "adopted")]
    assert ledger_entries(conn)[0]["status"] == "adopted"
    conn.close()


def test_lapsed_when_14_days_and_unchanged(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="repeated-error-loop"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_at = datetime.fromisoformat(ledger_entries(conn)[0]["updated_at"])
    accepted_epoch = accepted_at.timestamp()
    for i in range(3):
        _seed_session(conn, f"/b{i}", accepted_epoch - 1000 - i, errors=2)
    for i in range(5):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i, errors=2)
    now = accepted_at + timedelta(days=15)
    transitions = evaluate_follow_through(conn, now=now)
    assert transitions == [(row["id"], "repeated-error-loop", "lapsed")]
    assert ledger_entries(conn)[0]["status"] == "lapsed"
    conn.close()


def test_no_transition_when_after_count_below_minimum(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="repeated-error-loop"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(conn, f"/b{i}", accepted_epoch - 1000 - i, errors=4)
    # only 4 after-sessions, below MIN_AFTER=5
    for i in range(4):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i, errors=1)
    transitions = evaluate_follow_through(conn)
    assert transitions == []
    assert ledger_entries(conn)[0]["status"] == "accepted"
    conn.close()


def test_unmapped_fix_id_untouched(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="undo-revert-language"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(conn, f"/b{i}", accepted_epoch - 1000 - i, errors=4)
    for i in range(5):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i, errors=0)
    transitions = evaluate_follow_through(conn)
    assert transitions == []
    assert ledger_entries(conn)[0]["status"] == "accepted"
    conn.close()


def test_now_none_defaults_to_real_now_smoke(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="repeated-error-loop"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(conn, f"/b{i}", accepted_epoch - 1000 - i, errors=4)
    for i in range(5):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i, errors=1)
    transitions = evaluate_follow_through(conn)
    assert transitions == [(row["id"], "repeated-error-loop", "adopted")]
    conn.close()
