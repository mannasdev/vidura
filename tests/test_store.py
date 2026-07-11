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


def test_open_db_sets_wal_and_busy_timeout(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()


def test_open_db_creates_sessions_mtime_and_suggestions_status_indexes(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_sessions_mtime" in indexes
    assert "idx_suggestions_status" in indexes
    conn.close()


def test_open_db_index_creation_idempotent_on_reopen(tmp_path):
    p = tmp_path / "db.sqlite"
    open_db(p).close()
    conn = open_db(p)  # second open: CREATE INDEX IF NOT EXISTS must not error
    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_sessions_mtime" in indexes
    assert "idx_suggestions_status" in indexes
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


def test_mark_reflected_accepts_explicit_mtime_and_size(tmp_path):
    """A caller can stamp a session with stats captured earlier (e.g. at
    gather time), rather than the file's CURRENT (possibly grown) stats —
    otherwise a session that grows mid-sweep never gets its appended tail
    reflected."""
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    stale_mtime = p.stat().st_mtime
    stale_size = p.stat().st_size
    # file grows AFTER we captured the stale stats above
    p.write_text('{"more": "content grew"}', encoding="utf-8")
    mark_reflected(conn, p, mtime=stale_mtime, size=stale_size)
    # needs_reflection compares against the file's real (grown) stats,
    # so stamping with stale stats must leave it needing reflection again
    assert needs_reflection(conn, p) is True
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


from vidura.store import SCHEMA_VERSION


def test_migration_sets_user_version(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_migration_idempotent_on_existing_db(tmp_path):
    p = tmp_path / "db.sqlite"
    open_db(p).close()
    conn = open_db(p)  # second open: ALTERs must not re-run
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert {"streaks", "errors", "duration_seconds"} <= cols
    conn.close()


def test_migration_drops_chunk_tables_and_triggers(tmp_path):
    """v6: supermemory replaces the homegrown FTS5 chunk store — a fresh
    db never creates chunks/chunks_fts/their triggers at all."""
    conn = open_db(tmp_path / "db.sqlite")
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "chunks" not in tables
    assert "chunks_fts" not in tables
    triggers = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert "chunks_ai" not in triggers
    assert "chunks_ad" not in triggers
    conn.close()


def test_migration_drops_chunk_tables_from_pre_v6_db(tmp_path):
    """A db that already has v2-era chunks/chunks_fts (simulating an
    existing install) gets them dropped on upgrade to v6, while state
    tables are untouched."""
    p = tmp_path / "db.sqlite"
    conn = open_db(p)
    conn.execute("PRAGMA user_version = 5")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_path TEXT NOT NULL,
            text TEXT NOT NULL,
            user_turns INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text, content='chunks', content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
        END;
        """
    )
    conn.execute("INSERT INTO chunks(session_path, text, user_turns, created_at) VALUES ('/s/a', 'hi', 0, 'now')")
    conn.commit()
    conn.close()

    conn = open_db(p)  # reopen: migrates 5 -> 6, dropping chunk tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "chunks" not in tables
    assert "chunks_fts" not in tables
    # state tables untouched
    assert "sessions" in tables
    assert "suggestions" in tables
    assert "executions" in tables
    assert "character_history" in tables
    conn.close()


def test_migration_v6_idempotent_on_reopen(tmp_path):
    p = tmp_path / "db.sqlite"
    open_db(p).close()
    conn = open_db(p)  # second open: DROP IF EXISTS must not error
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_mark_reflected_stores_signal_columns(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p, streaks=3, errors=1, duration_seconds=120.0)
    row = conn.execute("SELECT streaks, errors, duration_seconds FROM sessions").fetchone()
    assert (row["streaks"], row["errors"], row["duration_seconds"]) == (3, 1, 120.0)
    conn.close()


def test_fresh_db_has_tools_used_column(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "tools_used" in cols
    conn.close()


def test_v6_db_migrates_in_place_to_v7(tmp_path):
    p = tmp_path / "db.sqlite"
    conn = open_db(p)
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()
    conn = open_db(p)  # reopen: must migrate 6 -> 7 without touching v6 tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "tools_used" in cols
    conn.close()


def test_migration_v7_idempotent_on_reopen(tmp_path):
    p = tmp_path / "db.sqlite"
    open_db(p).close()
    conn = open_db(p)  # second open: ALTER must not re-run
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "tools_used" in cols
    conn.close()


def test_old_session_row_tolerates_null_tools_used(tmp_path):
    """A session row written by an old (pre-v7) mark_reflected call, or
    one that simply didn't pass tools_used, stores NULL — reading it
    back must not raise."""
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p, streaks=1, errors=0, duration_seconds=10.0)  # no tools_used
    row = conn.execute("SELECT tools_used FROM sessions WHERE path = ?", (str(p),)).fetchone()
    assert row["tools_used"] is None
    conn.close()


def test_mark_reflected_stores_and_roundtrips_tools_used(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(
        conn, p, streaks=1, errors=0, duration_seconds=10.0,
        tools_used={"Read": 3, "mcp__playwright__click": 2},
    )
    row = conn.execute("SELECT tools_used FROM sessions WHERE path = ?", (str(p),)).fetchone()
    import json as _json
    assert _json.loads(row["tools_used"]) == {"Read": 3, "mcp__playwright__click": 2}
    conn.close()


def test_mark_reflected_tools_used_upserts(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p, tools_used={"Read": 1})
    mark_reflected(conn, p, tools_used={"Read": 5, "Bash": 1})
    row = conn.execute("SELECT tools_used FROM sessions WHERE path = ?", (str(p),)).fetchone()
    import json as _json
    assert _json.loads(row["tools_used"]) == {"Read": 5, "Bash": 1}
    conn.close()


def test_mark_reflected_empty_dict_tools_used_stored_as_empty_json(tmp_path):
    """An empty dict (a quiet session with truly no tool calls) is
    distinguishable from NULL (a caller that never passed the arg)."""
    conn = open_db(tmp_path / "db.sqlite")
    p = _session_file(tmp_path)
    mark_reflected(conn, p, tools_used={})
    row = conn.execute("SELECT tools_used FROM sessions WHERE path = ?", (str(p),)).fetchone()
    assert row["tools_used"] == "{}"
    conn.close()


def test_adopted_and_lapsed_block_resuggestion(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row_id = ledger_entries(conn)[0]["id"]
    set_status(conn, row_id, "adopted")
    record_suggestion(conn, _sugg(confidence=0.95))
    assert ledger_entries(conn, status="pending") == []
    assert "judge-executor-split" in blocked_fix_ids(conn)
    conn.close()


from vidura.store import executions_for, record_execution


def test_fresh_db_migrates_straight_to_v3(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "executions" in tables
    conn.close()


def test_v2_db_migrates_in_place_to_v3(tmp_path):
    p = tmp_path / "db.sqlite"
    conn = open_db(p)
    conn.execute("PRAGMA user_version = 2")
    conn.execute("DROP TABLE executions")
    conn.commit()
    conn.close()
    conn = open_db(p)  # reopen: must migrate 2 -> latest without touching v2 tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "executions" in tables
    assert "chunks" not in tables  # v6 migration drops it (supermemory replaces it)
    conn.close()


def test_record_execution_and_fetch_roundtrip(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    exec_id = record_execution(
        conn,
        suggestion_id=1,
        fix_id="github-context-by-paste",
        tier=3,
        detail="brew install gh",
        status="done",
        exit_code=0,
        output_head="Installing gh...",
    )
    rows = executions_for(conn, 1)
    assert len(rows) == 1
    assert rows[0]["id"] == exec_id
    assert rows[0]["fix_id"] == "github-context-by-paste"
    assert rows[0]["tier"] == 3
    assert rows[0]["status"] == "done"
    assert rows[0]["exit_code"] == 0
    assert rows[0]["started_at"]
    assert rows[0]["finished_at"]
    conn.close()


def test_record_execution_declined_status(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_execution(
        conn,
        suggestion_id=2,
        fix_id="missing-claude-md",
        tier=2,
        detail="append CLAUDE.md starter block",
        status="declined",
    )
    rows = executions_for(conn, 2)
    assert len(rows) == 1
    assert rows[0]["status"] == "declined"
    assert rows[0]["exit_code"] is None
    conn.close()


from vidura.store import mark_celebrated


def test_fresh_db_migrates_straight_to_v4(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert SCHEMA_VERSION == 7
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(suggestions)")}
    assert "celebrated" in cols
    conn.close()


def test_v3_db_migrates_in_place_to_v4(tmp_path):
    p = tmp_path / "db.sqlite"
    conn = open_db(p)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    conn = open_db(p)  # reopen: must migrate 3 -> current without touching v3 tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(suggestions)")}
    assert "celebrated" in cols
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "executions" in tables  # v3 migration didn't re-run/duplicate
    conn.close()


def test_new_suggestions_default_celebrated_zero(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row = ledger_entries(conn)[0]
    assert row["celebrated"] == 0
    conn.close()


def test_mark_celebrated_roundtrip(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg())
    row_id = ledger_entries(conn)[0]["id"]
    assert mark_celebrated(conn, row_id) is True
    row = conn.execute("SELECT celebrated FROM suggestions WHERE id = ?", (row_id,)).fetchone()
    assert row["celebrated"] == 1
    conn.close()


def test_mark_celebrated_missing_id_returns_false(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    assert mark_celebrated(conn, 999) is False
    conn.close()


def test_executions_for_scoped_to_suggestion(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_execution(conn, 1, "fix-a", 1, "detail", "done")
    record_execution(conn, 2, "fix-b", 1, "detail", "done")
    assert len(executions_for(conn, 1)) == 1
    assert len(executions_for(conn, 2)) == 1
    conn.close()


from datetime import datetime, timedelta, timezone

from vidura.store import expire_stale_pending


def _set_updated_at(conn, suggestion_id, when: datetime) -> None:
    conn.execute(
        "UPDATE suggestions SET updated_at = ? WHERE id = ?",
        (when.isoformat(), suggestion_id),
    )
    conn.commit()


def test_expire_stale_pending_flips_only_old_pending(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="old-one"))
    record_suggestion(conn, _sugg(fix_id="fresh-one"))
    rows = ledger_entries(conn)
    old_id = next(r["id"] for r in rows if r["fix_id"] == "old-one")
    fresh_id = next(r["id"] for r in rows if r["fix_id"] == "fresh-one")
    now = datetime.now(timezone.utc)
    _set_updated_at(conn, old_id, now - timedelta(days=15))
    _set_updated_at(conn, fresh_id, now - timedelta(days=1))

    expired_ids = expire_stale_pending(conn, now=now, days=14)

    assert expired_ids == [old_id]
    old_row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (old_id,)).fetchone()
    fresh_row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (fresh_id,)).fetchone()
    assert old_row["status"] == "expired"
    assert fresh_row["status"] == "pending"
    conn.close()


def test_expire_stale_pending_ignores_non_pending_statuses(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="accepted-one"))
    record_suggestion(conn, _sugg(fix_id="dismissed-one"))
    rows = ledger_entries(conn)
    accepted_id = next(r["id"] for r in rows if r["fix_id"] == "accepted-one")
    dismissed_id = next(r["id"] for r in rows if r["fix_id"] == "dismissed-one")
    set_status(conn, accepted_id, "accepted")
    set_status(conn, dismissed_id, "dismissed")
    now = datetime.now(timezone.utc)
    _set_updated_at(conn, accepted_id, now - timedelta(days=30))
    _set_updated_at(conn, dismissed_id, now - timedelta(days=30))

    expired_ids = expire_stale_pending(conn, now=now, days=14)

    assert expired_ids == []
    accepted_row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (accepted_id,)).fetchone()
    dismissed_row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (dismissed_id,)).fetchone()
    assert accepted_row["status"] == "accepted"
    assert dismissed_row["status"] == "dismissed"
    conn.close()


def test_expire_stale_pending_boundary_exactly_14_days_not_expired(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="boundary-one"))
    row_id = ledger_entries(conn)[0]["id"]
    now = datetime.now(timezone.utc)
    _set_updated_at(conn, row_id, now - timedelta(days=14))

    expired_ids = expire_stale_pending(conn, now=now, days=14)

    assert expired_ids == []
    row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "pending"
    conn.close()


def test_expire_stale_pending_just_over_boundary_expires(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="just-over"))
    row_id = ledger_entries(conn)[0]["id"]
    now = datetime.now(timezone.utc)
    _set_updated_at(conn, row_id, now - timedelta(days=14, seconds=1))

    expired_ids = expire_stale_pending(conn, now=now, days=14)

    assert expired_ids == [row_id]
    row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "expired"
    conn.close()


def test_expired_does_not_block_fix_id_and_does_not_absorb_new_pending(tmp_path):
    """CRITICAL SEMANTICS: expiry is 'aged out undecided', not a verdict.
    An expired row must not be added to blocked_fix_ids, and a fresh
    recording of the same fix_id must create a NEW pending row rather
    than merging into the expired one (merge path only targets
    status='pending' rows)."""
    conn = open_db(tmp_path / "db.sqlite")
    record_suggestion(conn, _sugg(fix_id="recurring-friction", confidence=0.7, evidence=["old evidence"]))
    old_id = ledger_entries(conn)[0]["id"]
    now = datetime.now(timezone.utc)
    _set_updated_at(conn, old_id, now - timedelta(days=20))

    expired_ids = expire_stale_pending(conn, now=now, days=14)
    assert expired_ids == [old_id]

    # not blocked — a fresh recurrence with new evidence must be allowed
    assert "recurring-friction" not in blocked_fix_ids(conn)

    # new recording creates a NEW pending row, not merged into the expired one
    record_suggestion(conn, _sugg(fix_id="recurring-friction", confidence=0.9, evidence=["fresh evidence"]))
    rows = conn.execute(
        "SELECT * FROM suggestions WHERE fix_id = ? ORDER BY id", ("recurring-friction",)
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == "expired"
    assert rows[0]["id"] == old_id
    import json as _json
    assert _json.loads(rows[0]["evidence"]) == ["old evidence"]  # untouched by the merge
    assert rows[1]["status"] == "pending"
    assert _json.loads(rows[1]["evidence"]) == ["fresh evidence"]  # new row, not merged
    conn.close()
