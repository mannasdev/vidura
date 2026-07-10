import sqlite3

from vidura.store import open_db


def test_open_db_creates_file_and_schema(tmp_path):
    db_path = tmp_path / "sub" / "vidura.db"
    conn = open_db(db_path)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "sessions" in tables
    assert "suggestions" in tables
    assert db_path.exists()
    conn.close()


def test_open_db_is_idempotent(tmp_path):
    db_path = tmp_path / "vidura.db"
    open_db(db_path).close()
    conn = open_db(db_path)  # second open must not fail on existing schema
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    conn.close()


def test_open_db_env_override(tmp_path, monkeypatch):
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db_path))
    conn = open_db()
    assert db_path.exists()
    conn.close()


from vidura.store import mark_reflected, needs_reflection


def _session_file(tmp_path, name="s.jsonl", content="{}"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_unseen_session_needs_reflection(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    assert needs_reflection(conn, p) is True
    conn.close()


def test_marked_session_does_not_need_reflection(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p)
    assert needs_reflection(conn, p) is False
    conn.close()


def test_changed_session_needs_reflection_again(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p)
    p.write_text('{"more": "content grew"}', encoding="utf-8")
    assert needs_reflection(conn, p) is True
    conn.close()


def test_mark_reflected_upserts(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p)
    p.write_text('{"grown": true}', encoding="utf-8")
    mark_reflected(conn, p)  # second call must update, not raise
    assert needs_reflection(conn, p) is False
    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 1
    conn.close()


from vidura.contract import Suggestion
from vidura.store import (
    blocked_fix_ids,
    ledger_entries,
    ledger_summary_for_prompt,
    record_suggestion,
    set_status,
)


def _sugg(fix_id="judge-executor-split", confidence=0.8, evidence=None, novel=False):
    return Suggestion(
        fix_id=fix_id,
        confidence=confidence,
        evidence=evidence or ["some quote"],
        blunt_summary="a blunt sentence",
        novel=novel,
    )


def test_record_and_list_pending(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    rows = ledger_entries(conn, status="pending")
    assert len(rows) == 1
    assert rows[0]["fix_id"] == "judge-executor-split"
    conn.close()


def test_pending_same_fix_id_merges_not_duplicates(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(confidence=0.7, evidence=["quote A"]))
    record_suggestion(conn, _sugg(confidence=0.9, evidence=["quote B"]))
    rows = ledger_entries(conn, status="pending")
    assert len(rows) == 1
    assert rows[0]["confidence"] == 0.9  # max wins
    assert rows[0]["occurrences"] == 2
    import json as _json
    evidence = _json.loads(rows[0]["evidence"])
    assert "quote A" in evidence and "quote B" in evidence
    conn.close()


def test_evidence_pool_capped_at_five(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    for i in range(8):
        record_suggestion(conn, _sugg(evidence=[f"quote {i}"]))
    import json as _json
    rows = ledger_entries(conn, status="pending")
    assert len(_json.loads(rows[0]["evidence"])) == 5
    conn.close()


def test_dismissed_fix_id_never_recorded_again(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row_id = ledger_entries(conn)[0]["id"]
    assert set_status(conn, row_id, "dismissed") is True
    record_suggestion(conn, _sugg(confidence=0.99))
    assert ledger_entries(conn, status="pending") == []
    assert "judge-executor-split" in blocked_fix_ids(conn)
    conn.close()


def test_novel_suggestions_never_merge_or_block(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="novel", novel=True))
    row_id = ledger_entries(conn)[0]["id"]
    set_status(conn, row_id, "dismissed")
    record_suggestion(conn, _sugg(fix_id="novel", novel=True))
    assert len(ledger_entries(conn, status="pending")) == 1
    assert "novel" not in blocked_fix_ids(conn)
    conn.close()


def test_set_status_unknown_id_returns_false(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert set_status(conn, 999, "accepted") is False
    conn.close()


def test_ledger_summary_for_prompt_shape(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    summary = ledger_summary_for_prompt(conn)
    assert summary[0]["fix_id"] == "judge-executor-split"
    assert summary[0]["status"] == "pending"
    assert "evidence" not in summary[0]  # keep the prompt lean
    conn.close()


def test_ledger_summary_for_prompt_caps_novel_rows(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    for i in range(15):
        record_suggestion(conn, _sugg(fix_id="novel", novel=True, evidence=[f"novel quote {i}"]))
    record_suggestion(conn, _sugg(fix_id="judge-executor-split"))
    record_suggestion(conn, _sugg(fix_id="context-window-overflow"))
    summary = ledger_summary_for_prompt(conn)
    assert len(summary) == 12  # 2 non-novel + 10 most recent novel


def test_record_suggestion_forces_novel_semantics_for_fix_id_novel(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="novel", novel=False))
    row_id = ledger_entries(conn)[0]["id"]
    set_status(conn, row_id, "dismissed")
    # a second suggestion with fix_id "novel" (novel flag False) must still
    # insert fresh rather than being blocked by the dismissed row above
    record_suggestion(conn, _sugg(fix_id="novel", novel=False, confidence=0.99))
    assert len(ledger_entries(conn, status="pending")) == 1
    assert "novel" not in blocked_fix_ids(conn)
    conn.close()
