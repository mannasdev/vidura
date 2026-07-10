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
