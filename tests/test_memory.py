from datetime import datetime, timedelta, timezone

import pytest

import vidura.memory as memory
from vidura.memory import (
    ChunkHit,
    breaker_tripped,
    get_context,
    memory_status,
    remember_chunks,
    search_chunks,
    search_sessions,
)
from vidura.store import open_db


def _db(tmp_path):
    return open_db(tmp_path / "db.sqlite")


@pytest.fixture(autouse=True)
def _clean_memory_state(monkeypatch):
    """Every test starts memory-less (no key) with a fresh circuit
    breaker — module-level breaker state is process-lifetime by design,
    so tests must reset it explicitly."""
    monkeypatch.delenv("SUPERMEMORY_CC_API_KEY", raising=False)
    monkeypatch.delenv("VIDURA_SUPERMEMORY_URL", raising=False)
    monkeypatch.delenv("VIDURA_SUPERMEMORY_ALLOW_REMOTE", raising=False)
    memory._reset_breaker_for_tests()
    yield
    memory._reset_breaker_for_tests()


def _activate(monkeypatch, url=None):
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    if url is not None:
        monkeypatch.setenv("VIDURA_SUPERMEMORY_URL", url)


# --- memory-less mode (no key) ---


def test_no_key_remember_chunks_no_ops(tmp_path):
    conn = _db(tmp_path)
    # must not raise, must not touch the network layer
    remember_chunks(conn, "/s/a.jsonl", ["[user] npm error"])
    conn.close()


def test_no_key_search_chunks_returns_empty_no_stderr(tmp_path, capsys):
    conn = _db(tmp_path)
    assert search_chunks(conn, ["npm error"]) == []
    captured = capsys.readouterr()
    assert captured.err == ""
    conn.close()


def test_no_key_memory_status_off(tmp_path):
    assert memory_status() == "off"


def test_no_key_never_calls_supermemory_request(monkeypatch, tmp_path):
    conn = _db(tmp_path)

    def fail(*a, **kw):
        raise AssertionError("supermemory must not be called without a key")

    monkeypatch.setattr(memory, "_supermemory_request", fail)
    remember_chunks(conn, "/s/a.jsonl", ["[user] chunk"])
    assert search_chunks(conn, ["chunk"]) == []
    conn.close()


# --- push payload shape ---


def test_remember_chunks_push_payload_shape(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    calls = []

    def fake_request(cfg, method, path, body=None):
        calls.append((method, path, body))
        if path == "/v3/documents/list":
            return {"memories": []}
        if path == "/v3/documents":
            return {"id": "doc_1", "status": "queued"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    remember_chunks(conn, "/very/private/client-x/session-abc.jsonl", ["[user] first chunk", "[user] second chunk"])

    list_calls = [b for m, p, b in calls if p == "/v3/documents/list"]
    assert len(list_calls) == 1
    assert list_calls[0]["containerTags"] == ["vidura"]
    assert list_calls[0]["filters"]["AND"][0]["value"] == "session-abc.jsonl"

    create_calls = [b for m, p, b in calls if p == "/v3/documents"]
    assert len(create_calls) == 2
    for i, body in enumerate(create_calls):
        assert body["containerTag"] == "vidura"
        assert body["metadata"]["session_basename"] == "session-abc.jsonl"
        assert body["metadata"]["chunk_index"] == i
        assert "created_at" in body["metadata"]
        # privacy: NEVER the full path in metadata
        assert "private" not in str(body["metadata"])
        assert "client-x" not in str(body["metadata"])
    assert create_calls[0]["content"] == "[user] first chunk"
    assert create_calls[1]["content"] == "[user] second chunk"
    conn.close()


def test_remember_chunks_skips_push_when_no_chunks(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    def fail(*a, **kw):
        raise AssertionError("must not call supermemory for an empty chunk list")

    monkeypatch.setattr(memory, "_supermemory_request", fail)
    remember_chunks(conn, "/s/a.jsonl", [])
    conn.close()


# --- idempotent re-push, tag-scoped ---


def test_remember_chunks_repush_lists_scoped_by_tag_and_basename(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
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

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    remember_chunks(conn, "/s/a.jsonl", ["[user] updated chunk"])

    list_calls = [b for m, p, b in calls if p == "/v3/documents/list"]
    assert list_calls[0]["containerTags"] == ["vidura"]  # tag conjunct: mandatory bug fix
    delete_calls = [b for m, p, b in calls if p == "/v3/documents/bulk"]
    assert len(delete_calls) == 1
    assert set(delete_calls[0]["ids"]) == {"doc_old_1", "doc_old_2"}
    conn.close()


def test_remember_chunks_no_delete_when_nothing_existing(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    calls = []

    def fake_request(cfg, method, path, body=None):
        calls.append((method, path, body))
        if path == "/v3/documents/list":
            return {"memories": []}
        if path == "/v3/documents":
            return {"id": "doc_1", "status": "queued"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    remember_chunks(conn, "/s/a.jsonl", ["[user] chunk"])
    assert not any(p == "/v3/documents/bulk" for _, p, _ in calls)
    conn.close()


# --- search: parse, exclusion, age filter ---


def _search_response(results):
    return {"results": results}


def test_search_chunks_parses_hits(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()

    def fake_request(cfg, method, path, body=None):
        assert path == "/v3/search"
        assert body["containerTag"] == "vidura"
        return _search_response(
            [
                {
                    "score": 0.9,
                    "metadata": {"session_basename": "s1.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] timeout seen before"}],
                }
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    hits = search_chunks(conn, ["timeout"], k=5)
    assert len(hits) == 1
    assert hits[0].session_path == "s1.jsonl"
    assert hits[0].text == "[user] timeout seen before"
    assert hits[0].score == 0.9
    conn.close()


def test_search_chunks_exclusion_maps_full_paths_to_basenames(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()

    def fake_request(cfg, method, path, body=None):
        return _search_response(
            [
                {
                    "score": 0.9,
                    "metadata": {"session_basename": "excluded.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] excluded hit"}],
                },
                {
                    "score": 0.5,
                    "metadata": {"session_basename": "kept.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] kept hit"}],
                },
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    hits = search_chunks(
        conn, ["timeout"], k=5, exclude_sessions={"/full/path/to/excluded.jsonl"}
    )
    assert {h.session_path for h in hits} == {"kept.jsonl"}
    conn.close()


def test_search_chunks_age_filter_drops_old_hits(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    fresh = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()

    def fake_request(cfg, method, path, body=None):
        return _search_response(
            [
                {
                    "score": 0.9,
                    "metadata": {"session_basename": "old.jsonl", "created_at": stale},
                    "chunks": [{"content": "[user] ancient friction"}],
                },
                {
                    "score": 0.5,
                    "metadata": {"session_basename": "new.jsonl", "created_at": fresh},
                    "chunks": [{"content": "[user] recent friction"}],
                },
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    hits = search_chunks(conn, ["friction"], k=5)
    assert {h.session_path for h in hits} == {"new.jsonl"}
    conn.close()


def test_search_chunks_missing_created_at_dropped(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    def fake_request(cfg, method, path, body=None):
        return _search_response(
            [
                {
                    "score": 0.9,
                    "metadata": {"session_basename": "no-date.jsonl"},
                    "chunks": [{"content": "[user] no created_at"}],
                }
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    assert search_chunks(conn, ["friction"], k=5) == []
    conn.close()


def test_search_chunks_boundary_exactly_90_days_kept(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    boundary = (datetime.now(timezone.utc) - timedelta(days=89, hours=23)).isoformat()

    def fake_request(cfg, method, path, body=None):
        return _search_response(
            [
                {
                    "score": 0.9,
                    "metadata": {"session_basename": "s.jsonl", "created_at": boundary},
                    "chunks": [{"content": "[user] just inside the window"}],
                }
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    hits = search_chunks(conn, ["window"], k=5)
    assert len(hits) == 1
    conn.close()


def test_search_chunks_empty_terms_returns_empty_without_request(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    def fail(*a, **kw):
        raise AssertionError("must not call supermemory for empty terms")

    monkeypatch.setattr(memory, "_supermemory_request", fail)
    assert search_chunks(conn, []) == []
    conn.close()


# --- circuit breaker ---


def test_breaker_trips_on_request_failure(monkeypatch, tmp_path, capsys):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    def fake_request(cfg, method, path, body=None):
        raise ConnectionError("supermemory unreachable")

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    assert search_chunks(conn, ["x"]) == []
    assert breaker_tripped() is True
    assert "circuit breaker tripped" in capsys.readouterr().err
    conn.close()


def test_breaker_trips_on_cumulative_latency(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    clock = {"t": 0.0}

    def fake_monotonic():
        return clock["t"]

    def fake_urlopen(req, timeout=None):
        clock["t"] += 31.0  # exceeds the 30s cumulative wall-time budget

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b'{"results": []}'

        return _Resp()

    monkeypatch.setattr(memory.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(memory.urllib.request, "urlopen", fake_urlopen)

    search_chunks(conn, ["x"])
    assert breaker_tripped() is True
    conn.close()


def test_breaker_skip_after_trip_never_calls_request_again(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    calls = []

    def fake_request(cfg, method, path, body=None):
        calls.append(path)
        raise ConnectionError("down")

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    search_chunks(conn, ["x"])  # trips it
    assert len(calls) == 1
    search_chunks(conn, ["x"])  # must skip instantly, no second request
    remember_chunks(conn, "/s/a.jsonl", ["chunk"])
    assert len(calls) == 1
    conn.close()


def test_breaker_stderr_note_printed_exactly_once(monkeypatch, tmp_path, capsys):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    def fake_request(cfg, method, path, body=None):
        raise ConnectionError("down")

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    search_chunks(conn, ["x"])
    search_chunks(conn, ["y"])
    search_chunks(conn, ["z"])
    err = capsys.readouterr().err
    assert err.count("circuit breaker tripped") == 1
    conn.close()


def test_breaker_tripped_reflected_in_memory_status(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)

    def fake_request(cfg, method, path, body=None):
        raise ConnectionError("down")

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    search_chunks(conn, ["x"])
    assert memory_status() == "breaker-tripped"
    conn.close()


# --- remote gate (3 branches) ---


def test_remote_gate_localhost_url_allowed(monkeypatch, tmp_path):
    _activate(monkeypatch, url="http://localhost:6767")
    assert memory._supermemory_config() == ("http://localhost:6767", "sm_test_key")


def test_remote_gate_blocks_remote_url_without_allow_flag(monkeypatch, tmp_path, capsys):
    _activate(monkeypatch, url="http://example.com:6767")
    assert memory._supermemory_config() is None
    err = capsys.readouterr().err
    assert err.count("\n") == 1  # exactly one stderr line
    assert "example.com" in err


def test_remote_gate_allows_remote_url_with_allow_flag(monkeypatch, tmp_path):
    _activate(monkeypatch, url="http://example.com:6767")
    monkeypatch.setenv("VIDURA_SUPERMEMORY_ALLOW_REMOTE", "1")
    assert memory._supermemory_config() == ("http://example.com:6767", "sm_test_key")


def test_remote_gate_never_raises(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch, url="http://example.com:6767")
    # must not raise — remember_chunks/search_chunks just no-op
    remember_chunks(conn, "/s/a.jsonl", ["[user] chunk"])
    assert search_chunks(conn, ["chunk"]) == []
    conn.close()


# --- search_sessions / get_context: single-scale ordering ---


def test_search_sessions_orders_by_score_descending(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()

    def fake_request(cfg, method, path, body=None):
        return _search_response(
            [
                {
                    "score": 0.4,
                    "metadata": {"session_basename": "low.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] low relevance"}],
                },
                {
                    "score": 0.95,
                    "metadata": {"session_basename": "high.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] high relevance"}],
                },
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    sessions = search_sessions(conn, ["relevance"])
    assert sessions[0][0] == "high.jsonl"
    assert sessions[0][1] > sessions[1][1]
    conn.close()


def test_search_sessions_empty_when_memory_off(tmp_path):
    conn = _db(tmp_path)
    assert search_sessions(conn, ["anything"]) == []
    conn.close()


def test_get_context_respects_token_budget(monkeypatch, tmp_path):
    conn = _db(tmp_path)
    _activate(monkeypatch)
    now = datetime.now(timezone.utc).isoformat()

    def fake_request(cfg, method, path, body=None):
        return _search_response(
            [
                {
                    "score": 0.9,
                    "metadata": {"session_basename": "a.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] timeout " + "x" * 8000}],
                },
                {
                    "score": 0.8,
                    "metadata": {"session_basename": "b.jsonl", "created_at": now},
                    "chunks": [{"content": "[user] timeout " + "y" * 8000}],
                },
            ]
        )

    monkeypatch.setattr(memory, "_supermemory_request", fake_request)
    ctx = get_context(conn, ["timeout"], token_budget=1000)  # ~4000 chars
    assert 0 < len(ctx) <= 4200
    conn.close()


def test_get_context_empty_when_memory_off(tmp_path):
    conn = _db(tmp_path)
    assert get_context(conn, ["timeout"], token_budget=1000) == ""
    conn.close()
