from datetime import datetime, timedelta, timezone

from vidura.memory import (
    get_context,
    prune_chunks,
    remember_chunks,
    search_chunks,
    search_sessions,
)
from vidura.store import open_db


def _db(tmp_path):
    return open_db(tmp_path / "db.sqlite")


def test_remember_and_search_roundtrip(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ["[user] npm error ENEEDAUTH broke the publish"])
    remember_chunks(conn, "/s/b.jsonl", ["[user] css grid alignment question"])
    hits = search_chunks(conn, ["ENEEDAUTH"], k=5)
    assert len(hits) == 1
    assert hits[0].session_path == "/s/a.jsonl"
    conn.close()


def test_search_excludes_sessions(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ["[user] connection refused port 5432"])
    remember_chunks(conn, "/s/b.jsonl", ["[user] connection refused port 5432 again"])
    hits = search_chunks(conn, ["connection refused"], exclude_sessions={"/s/a.jsonl"})
    assert {h.session_path for h in hits} == {"/s/b.jsonl"}
    conn.close()


def test_search_exclusion_cannot_starve_results(tmp_path):
    conn = _db(tmp_path)
    # excluded session dominates the ranking with 20 matching chunks
    remember_chunks(conn, "/s/current.jsonl", [f"[user] timeout error variant {i}" for i in range(20)])
    remember_chunks(conn, "/s/history.jsonl", ["[user] timeout error seen once long ago"])
    hits = search_chunks(conn, ["timeout error"], k=5, exclude_sessions={"/s/current.jsonl"})
    assert len(hits) == 1
    assert hits[0].session_path == "/s/history.jsonl"
    conn.close()


def test_search_empty_terms_returns_empty(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ["[user] anything"])
    assert search_chunks(conn, []) == []
    conn.close()


def test_search_quotes_are_escaped(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ['[user] error "unexpected token" in parser'])
    hits = search_chunks(conn, ['error "unexpected token"'])  # must not raise
    assert len(hits) == 1
    conn.close()


def test_prune_deletes_old_chunks_and_fts_rows(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/old.jsonl", ["[user] ancient friction"])
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    conn.execute("UPDATE chunks SET created_at = ?", (old,))
    conn.commit()
    assert prune_chunks(conn, days=90) == 1
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert search_chunks(conn, ["ancient"]) == []  # FTS row gone too
    conn.close()


def test_search_sessions_groups_by_best_score(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ["[user] timeout error", "[user] timeout error twice"])
    remember_chunks(conn, "/s/b.jsonl", ["[user] unrelated"])
    sessions = search_sessions(conn, ["timeout"])
    assert sessions[0][0] == "/s/a.jsonl"
    assert len(sessions) == 1
    conn.close()


def test_remember_chunks_idempotent_per_session(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ["[user] first version"])
    remember_chunks(conn, "/s/a.jsonl", ["[user] first version", "[user] second chunk"])
    rows = conn.execute("SELECT COUNT(*) FROM chunks WHERE session_path='/s/a.jsonl'").fetchone()[0]
    assert rows == 2  # replaced, not appended
    assert len(search_chunks(conn, ["first version"])) == 1
    conn.close()


def test_get_context_respects_token_budget(tmp_path):
    conn = _db(tmp_path)
    remember_chunks(conn, "/s/a.jsonl", ["[user] timeout " + "x" * 8000])
    remember_chunks(conn, "/s/b.jsonl", ["[user] timeout " + "y" * 8000])
    ctx = get_context(conn, ["timeout"], token_budget=1000)  # ~4000 chars
    assert 0 < len(ctx) <= 4200
    conn.close()
