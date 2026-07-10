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
