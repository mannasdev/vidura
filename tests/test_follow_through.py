import json
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


def _seed_session(conn, path, mtime, streaks=0, errors=0, duration=0.0, tools_used=None):
    conn.execute(
        "INSERT INTO sessions(path, mtime, size, reflected_at, streaks, errors, duration_seconds, tools_used) "
        "VALUES (?, ?, 0, '2026-01-01T00:00:00+00:00', ?, ?, ?, ?)",
        (
            path,
            mtime,
            streaks,
            errors,
            duration,
            json.dumps(tools_used) if tools_used is not None else None,
        ),
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


# ---------------------------------------------------------------------------
# tool-usage follow-through (manual-ui-verification / adoption_tool="playwright")
# ---------------------------------------------------------------------------


def test_tool_usage_adopted_when_three_post_accept_sessions_use_tool(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(
            conn, f"/a{i}", accepted_epoch + 1000 + i,
            tools_used={"mcp__playwright__click": 2},
        )
    transitions = evaluate_follow_through(conn)
    assert transitions == [(row["id"], "manual-ui-verification", "adopted")]
    assert ledger_entries(conn)[0]["status"] == "adopted"
    conn.close()


def test_tool_usage_adopted_match_is_case_insensitive_substring(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(
            conn, f"/a{i}", accepted_epoch + 1000 + i,
            tools_used={"MCP__PLAYWRIGHT__navigate": 1},
        )
    transitions = evaluate_follow_through(conn)
    assert transitions == [(row["id"], "manual-ui-verification", "adopted")]
    conn.close()


def test_tool_usage_lapsed_after_14_days_zero_usage(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_at = datetime.fromisoformat(ledger_entries(conn)[0]["updated_at"])
    accepted_epoch = accepted_at.timestamp()
    # post-accept sessions exist, but never touch playwright
    for i in range(5):
        _seed_session(
            conn, f"/a{i}", accepted_epoch + 1000 + i,
            tools_used={"Read": 3, "Bash": 1},
        )
    now = accepted_at + timedelta(days=15)
    transitions = evaluate_follow_through(conn, now=now)
    assert transitions == [(row["id"], "manual-ui-verification", "lapsed")]
    assert ledger_entries(conn)[0]["status"] == "lapsed"
    conn.close()


def test_tool_usage_lapsed_with_no_post_accept_sessions_at_all(tmp_path):
    """Zero usage includes the degenerate case of zero post-accept
    sessions (not just sessions that used other tools) — 14 days with
    nothing recorded is still "no measurable adoption"."""
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_at = datetime.fromisoformat(ledger_entries(conn)[0]["updated_at"])
    now = accepted_at + timedelta(days=15)
    transitions = evaluate_follow_through(conn, now=now)
    assert transitions == [(row["id"], "manual-ui-verification", "lapsed")]
    conn.close()


def test_tool_usage_pending_under_14_days_and_under_three_usages(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_at = datetime.fromisoformat(ledger_entries(conn)[0]["updated_at"])
    accepted_epoch = accepted_at.timestamp()
    # only 2 sessions used the tool, and well under 14 days elapsed
    for i in range(2):
        _seed_session(
            conn, f"/a{i}", accepted_epoch + 1000 + i,
            tools_used={"mcp__playwright__click": 1},
        )
    now = accepted_at + timedelta(days=1)
    transitions = evaluate_follow_through(conn, now=now)
    assert transitions == []
    assert ledger_entries(conn)[0]["status"] == "accepted"
    conn.close()


def test_tool_usage_pending_some_usage_but_under_14_days_not_lapsed(tmp_path):
    """1-2 sessions of usage, under the 14-day window: neither adopted
    (below MIN_TOOL_USAGE_SESSIONS) nor lapsed (below LAPSE_DAYS, and
    usage is nonzero anyway)."""
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_at = datetime.fromisoformat(ledger_entries(conn)[0]["updated_at"])
    accepted_epoch = accepted_at.timestamp()
    _seed_session(conn, "/a0", accepted_epoch + 1000, tools_used={"mcp__playwright__click": 1})
    now = accepted_at + timedelta(days=5)
    transitions = evaluate_follow_through(conn, now=now)
    assert transitions == []
    conn.close()


def test_tool_usage_fixes_without_adoption_tool_unaffected(tmp_path):
    """A regular (non-tool-usage) FIX_METRICS fix keeps working exactly
    as before — the tool-usage branch is additive, not a replacement."""
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="judge-executor-split"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(conn, f"/b{i}", accepted_epoch - 1000 - i, streaks=4)
    for i in range(5):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i, streaks=1)
    transitions = evaluate_follow_through(conn)
    assert transitions == [(row["id"], "judge-executor-split", "adopted")]
    conn.close()


def test_tool_usage_ignores_null_tools_used_rows(tmp_path):
    """Sessions with NULL tools_used (old pre-v7 rows, or sessions that
    never called mark_reflected with tools_used) don't crash and don't
    count as usage."""
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="manual-ui-verification"))
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    accepted_epoch = datetime.fromisoformat(
        ledger_entries(conn)[0]["updated_at"]
    ).timestamp()
    for i in range(3):
        _seed_session(conn, f"/a{i}", accepted_epoch + 1000 + i)  # tools_used=None
    transitions = evaluate_follow_through(conn)
    assert transitions == []
    assert ledger_entries(conn)[0]["status"] == "accepted"
    conn.close()
