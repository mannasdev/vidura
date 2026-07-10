from datetime import datetime, timedelta, timezone

from vidura.memory import (
    _supermemory_config,
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


# --- supermemory backend: config gating ---


def test_supermemory_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VIDURA_MEMORY_BACKEND", raising=False)
    assert _supermemory_config() is None


def test_supermemory_requires_api_key(monkeypatch):
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.delenv("SUPERMEMORY_CC_API_KEY", raising=False)
    assert _supermemory_config() is None


def test_supermemory_config_defaults_url(monkeypatch):
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    monkeypatch.delenv("VIDURA_SUPERMEMORY_URL", raising=False)
    assert _supermemory_config() == ("http://localhost:6767", "sm_test_key")


def test_supermemory_config_respects_custom_url(monkeypatch):
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    monkeypatch.setenv("VIDURA_SUPERMEMORY_URL", "http://example:9999")
    assert _supermemory_config() == ("http://example:9999", "sm_test_key")


# --- supermemory backend: remember_chunks push ---


def test_remember_chunks_pushes_new_chunks_to_supermemory(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    calls = []

    def fake_request(cfg, method, path, body=None):
        calls.append((method, path, body))
        if path == "/v3/documents/list":
            return {"memories": []}
        if path == "/v3/documents":
            return {"id": "doc_1", "status": "queued"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    remember_chunks(conn, "/s/a.jsonl", ["[user] first chunk", "[user] second chunk"])

    methods_paths = [(m, p) for m, p, _ in calls]
    assert ("POST", "/v3/documents/list") in methods_paths
    assert ("DELETE", "/v3/documents/bulk") not in methods_paths
    create_calls = [b for m, p, b in calls if p == "/v3/documents"]
    assert len(create_calls) == 2
    assert create_calls[0]["containerTag"] == "vidura"
    assert create_calls[0]["metadata"]["session_path"] == "/s/a.jsonl"
    assert create_calls[0]["taskType"] == "memory"
    conn.close()


def test_remember_chunks_repush_deletes_existing_supermemory_docs(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    calls = []

    def fake_request(cfg, method, path, body=None):
        calls.append((method, path, body))
        if path == "/v3/documents/list":
            return {"memories": [{"id": "doc_old_1"}, {"id": "doc_old_2"}]}
        if path == "/v3/documents/bulk":
            return {"success": True, "deletedCount": 2}
        if path == "/v3/documents":
            return {"id": "doc_new", "status": "queued"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    remember_chunks(conn, "/s/a.jsonl", ["[user] updated chunk"])

    delete_calls = [b for m, p, b in calls if p == "/v3/documents/bulk"]
    assert len(delete_calls) == 1
    assert set(delete_calls[0]["ids"]) == {"doc_old_1", "doc_old_2"}
    conn.close()


def test_remember_chunks_survives_supermemory_failure(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")

    def fake_request(cfg, method, path, body=None):
        raise ConnectionError("supermemory unreachable")

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    remember_chunks(conn, "/s/a.jsonl", ["[user] chunk"])  # must not raise

    rows = conn.execute("SELECT COUNT(*) FROM chunks WHERE session_path='/s/a.jsonl'").fetchone()[0]
    assert rows == 1  # local write still happened
    conn.close()


# --- supermemory backend: search_chunks blend ---


def test_search_chunks_backend_disabled_never_calls_supermemory(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.delenv("VIDURA_MEMORY_BACKEND", raising=False)
    remember_chunks(conn, "/s/a.jsonl", ["[user] timeout error"])

    def fake_request(*a, **kw):
        raise AssertionError("supermemory should not be called when backend is fts5")

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    hits = search_chunks(conn, ["timeout"])
    assert len(hits) == 1
    conn.close()


def test_search_chunks_blend_merges_supermemory_hits(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    remember_chunks(conn, "/s/local.jsonl", ["[user] timeout error locally"])

    def fake_request(cfg, method, path, body=None):
        assert path == "/v3/search"
        return {
            "results": [
                {
                    "documentId": "doc_remote",
                    "score": 0.9,
                    "metadata": {"session_path": "/s/remote.jsonl", "created_at": "2026-01-01T00:00:00+00:00"},
                    "chunks": [{"content": "[user] timeout seen in a past session", "isRelevant": True, "score": 0.9}],
                }
            ]
        }

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    hits = search_chunks(conn, ["timeout"], k=5)
    assert {h.session_path for h in hits} == {"/s/local.jsonl", "/s/remote.jsonl"}
    conn.close()


def test_search_chunks_blend_falls_back_on_supermemory_failure(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    remember_chunks(conn, "/s/local.jsonl", ["[user] timeout error locally"])

    def fake_request(cfg, method, path, body=None):
        raise TimeoutError("supermemory timed out")

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    hits = search_chunks(conn, ["timeout"], k=5)  # must not raise
    assert len(hits) == 1
    assert hits[0].session_path == "/s/local.jsonl"
    conn.close()


def test_search_chunks_blend_excludes_sessions_from_supermemory_too(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    monkeypatch.setenv("VIDURA_MEMORY_BACKEND", "blend")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")

    def fake_request(cfg, method, path, body=None):
        return {
            "results": [
                {
                    "documentId": "doc_excluded",
                    "score": 0.9,
                    "metadata": {"session_path": "/s/excluded.jsonl", "created_at": "2026-01-01T00:00:00+00:00"},
                    "chunks": [{"content": "[user] timeout excluded", "isRelevant": True, "score": 0.9}],
                },
                {
                    "documentId": "doc_kept",
                    "score": 0.8,
                    "metadata": {"session_path": "/s/kept.jsonl", "created_at": "2026-01-01T00:00:00+00:00"},
                    "chunks": [{"content": "[user] timeout kept", "isRelevant": True, "score": 0.8}],
                },
            ]
        }

    monkeypatch.setattr("vidura.memory._supermemory_request", fake_request)
    hits = search_chunks(conn, ["timeout"], k=5, exclude_sessions={"/s/excluded.jsonl"})
    assert {h.session_path for h in hits} == {"/s/kept.jsonl"}
    conn.close()
