import json
from pathlib import Path
from types import SimpleNamespace

from vidura.store import mark_reflected, open_db
from vidura.sweep import (
    PER_SESSION_CHUNK_BUDGET,
    SessionWork,
    gather_pending_work,
    pack_batches,
)


def _user_turn(text, ts="2026-07-01T10:00:00.000Z"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _assistant_turn(text, ts="2026-07-01T10:00:05.000Z", tool_use=False):
    content = [{"type": "text", "text": text}]
    if tool_use:
        content.append({"type": "tool_use", "name": "Read", "input": {}})
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": "m", "content": content}}


def _write_friction_session(dirpath: Path, name: str) -> Path:
    p = dirpath / name
    turns = [
        _user_turn("do the thing"),
        _user_turn("no, not like that"),
        _user_turn("still wrong"),
        _assistant_turn("ok", tool_use=True),
    ]
    p.write_text("\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")
    return p


def _write_calm_session(dirpath: Path, name: str) -> Path:
    p = dirpath / name
    turns = [_user_turn("one thing"), _assistant_turn("done", tool_use=True)]
    p.write_text("\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")
    return p


def test_gather_skips_calm_and_already_reflected(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    friction = _write_friction_session(root, "friction.jsonl")
    _write_calm_session(root, "calm.jsonl")
    seen = _write_friction_session(root, "seen.jsonl")
    mark_reflected(conn, seen)
    work = gather_pending_work(conn, root=root, window_days=30)
    assert [w.path for w in work] == [friction]
    assert work[0].streak_count == 1
    assert work[0].chunks
    conn.close()


def _write_tool_error_only_session(dirpath: Path, name: str) -> Path:
    """A session whose only friction is a repeated error INSIDE
    tool_result content (not an assistant turn, not a reprompt streak) —
    must not be treated as friction (tool_error_repeats never gates
    inclusion)."""
    p = dirpath / name
    tool_result_block = {
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": "Error: boom\nTraceback (most recent call last):"}],
        },
    }
    turns = [
        _user_turn("run the tests"),
        tool_result_block,
        tool_result_block,
        tool_result_block,
        _assistant_turn("ok", tool_use=True),
    ]
    p.write_text("\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")
    return p


def test_gather_tool_error_repeats_alone_does_not_count_as_friction(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    tool_error_only = _write_tool_error_only_session(root, "tool-errors.jsonl")
    work = gather_pending_work(conn, root=root, window_days=30)
    assert work == []  # gated out, marked reflected with zero stats instead
    row = conn.execute(
        "SELECT streaks, errors FROM sessions WHERE path = ?", (str(tool_error_only),)
    ).fetchone()
    assert (row["streaks"], row["errors"]) == (0, 0)
    conn.close()


def test_gather_marks_quiet_session_reflected_with_zero_stats(tmp_path):
    """No-friction sessions are stamped reflected (streaks=0/errors=0/
    duration=0) instead of being left unmarked — otherwise a quiet
    session gets re-parsed and re-redacted on every future sweep
    forever (outside-voice finding #8)."""
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    calm = _write_calm_session(root, "calm.jsonl")
    work = gather_pending_work(conn, root=root, window_days=30)
    assert work == []
    row = conn.execute("SELECT streaks, errors, duration_seconds FROM sessions WHERE path = ?", (str(calm),)).fetchone()
    assert row is not None
    assert (row["streaks"], row["errors"], row["duration_seconds"]) == (0, 0, 0.0)
    conn.close()


def test_gather_does_not_regather_quiet_session_next_call(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    _write_calm_session(root, "calm.jsonl")
    first = gather_pending_work(conn, root=root, window_days=30)
    assert first == []
    # second call: needs_reflection is now False for the quiet session,
    # so it's skipped outright (not even re-parsed) — nothing to assert
    # on chunks, just that it still yields no work and doesn't error.
    second = gather_pending_work(conn, root=root, window_days=30)
    assert second == []
    conn.close()


def test_gather_caps_per_session_chunks(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    p = root / "huge.jsonl"
    turns = []
    for i in range(40):
        turns.append(_user_turn(f"attempt {i} " + "x" * 3000))
        turns.append(_user_turn(f"retry {i} " + "y" * 3000))
    turns.append(_assistant_turn("ok", tool_use=True))
    p.write_text("\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")
    work = gather_pending_work(conn, root=root, window_days=30)
    total = sum(len(c) for c in work[0].chunks)
    assert total <= PER_SESSION_CHUNK_BUDGET
    conn.close()


def test_gather_captures_mtime_and_size_at_gather_time(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    friction = _write_friction_session(root, "friction.jsonl")
    st = friction.stat()
    work = gather_pending_work(conn, root=root, window_days=30)
    assert work[0].mtime == st.st_mtime
    assert work[0].size == st.st_size
    conn.close()


def test_sweep_survives_growth_during_batch(tmp_path):
    """A session that grows between gather and mark_reflected must still
    need re-reflection afterward — the stats captured at gather time
    (not the CURRENT, grown, file) are what gets stamped."""
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    friction = _write_friction_session(root, "friction.jsonl")
    work = gather_pending_work(conn, root=root, window_days=30)
    # simulate the file growing mid-batch, after gather captured its stats
    friction.write_text(friction.read_text() + json.dumps(_user_turn("appended tail")) + "\n", encoding="utf-8")
    with patch("vidura.sweep.reflect", return_value=_response()):
        run_sweep(conn, [work])
    assert needs_reflection(conn, friction) is True


def test_pack_batches_whole_sessions_densest_first():
    a = SessionWork(path=Path("a"), chunks=["x" * 30000], streak_count=5)
    b = SessionWork(path=Path("b"), chunks=["y" * 30000], streak_count=1)
    c = SessionWork(path=Path("c"), chunks=["z" * 10000], streak_count=9)
    batches = pack_batches([a, b, c], budget_chars=48000)
    # densest first: c (9 streaks) then a (5) fit batch 1; b spills to batch 2
    assert [w.path.name for w in batches[0]] == ["c", "a"]
    assert [w.path.name for w in batches[1]] == ["b"]


def test_pack_batches_oversized_session_gets_own_batch():
    big = SessionWork(path=Path("big"), chunks=["x" * 60000], streak_count=2)
    small = SessionWork(path=Path("s"), chunks=["y" * 1000], streak_count=1)
    batches = pack_batches([big, small], budget_chars=48000)
    assert len(batches) == 2
    assert batches[0][0].path.name == "big"


from unittest.mock import patch

from vidura.contract import CONTRACT_VERSION, ReflectResponse, Suggestion
from vidura.reflect import ReflectorError
from vidura.store import ledger_entries, needs_reflection
from vidura.sweep import run_sweep


def _work(tmp_path, name, streaks=1):
    p = _write_friction_session(tmp_path, name)
    st = p.stat()
    return SessionWork(
        path=p,
        chunks=[f"[user] chunk of {name}"],
        streak_count=streaks,
        mtime=st.st_mtime,
        size=st.st_size,
    )


def _response(fix_id="judge-executor-split", confidence=0.85):
    return ReflectResponse(
        contract_version=CONTRACT_VERSION,
        suggestions=[Suggestion(fix_id=fix_id, confidence=confidence, evidence=["q"], blunt_summary="s")],
    )


def test_run_sweep_records_and_marks(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, "a.jsonl")], [_work(tmp_path, "b.jsonl")]]
    with patch("vidura.sweep.reflect", return_value=_response()):
        stats = run_sweep(conn, batches)
    assert stats["batches_run"] == 2
    assert stats["sessions_reflected"] == 2
    assert not needs_reflection(conn, batches[0][0].path)
    rows = ledger_entries(conn, status="pending")
    assert len(rows) == 1  # same fix_id from both batches merged
    assert rows[0]["occurrences"] == 2
    conn.close()


def test_failed_batch_not_marked_and_sweep_continues(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, "a.jsonl")], [_work(tmp_path, "b.jsonl")]]
    responses = [ReflectorError("session limit"), _response()]
    def _side_effect(*args, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    with patch("vidura.sweep.reflect", side_effect=_side_effect):
        stats = run_sweep(conn, batches)
    assert stats["batches_failed"] == 1
    assert needs_reflection(conn, batches[0][0].path) is True   # resume target
    assert needs_reflection(conn, batches[1][0].path) is False
    conn.close()


def test_mark_reflected_failure_counts_batch_failed_and_continues(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, "a.jsonl")], [_work(tmp_path, "b.jsonl")]]
    with patch("vidura.sweep.reflect", return_value=_response()), \
         patch("vidura.sweep.mark_reflected", side_effect=[FileNotFoundError("gone"), None]):
        stats = run_sweep(conn, batches)
    assert stats["batches_failed"] == 1
    assert stats["batches_run"] == 1
    conn.close()


def test_max_batches_limits_work(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, f"{i}.jsonl")] for i in range(5)]
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        stats = run_sweep(conn, batches, max_batches=2)
    assert mock_reflect.call_count == 2
    assert stats["batches_run"] == 2
    conn.close()


def test_sweep_passes_ledger_to_reflector(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    from vidura.store import record_suggestion, set_status
    record_suggestion(conn, Suggestion(fix_id="repeated-error-loop", confidence=0.9, evidence=["e"], blunt_summary="old"))
    set_status(conn, ledger_entries(conn)[0]["id"], "dismissed")
    batches = [[_work(tmp_path, "a.jsonl")]]
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        run_sweep(conn, batches)
    request = mock_reflect.call_args[0][0]
    assert any(e["fix_id"] == "repeated-error-loop" and e["status"] == "dismissed" for e in request.ledger)
    conn.close()


from vidura.sweep import main


def test_print_ledger_report_strips_control_chars(tmp_path, capsys):
    conn = open_db(tmp_path / "db.sqlite")
    from vidura.store import record_suggestion
    record_suggestion(
        conn,
        Suggestion(
            fix_id="repeated-error-loop",
            confidence=0.9,
            evidence=["\x1b[31mred quote\x1b[0m"],
            blunt_summary="\x1b[31msummary with escape\x1b[0m",
        ),
    )
    from vidura.sweep import _print_ledger_report
    _print_ledger_report(conn)
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "summary with escape" in out
    assert "red quote" in out
    conn.close()


def test_main_no_pending_work(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    assert "Nothing new to sweep" in capsys.readouterr().out


def test_main_runs_and_prints_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    work = [_work(tmp_path, "a.jsonl", streaks=3)]
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: work)
    with patch("vidura.sweep.reflect", return_value=_response()):
        exit_code = main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "judge-executor-split" in out
    assert "1 batches run" in out


def test_main_batches_flag_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    work = [_work(tmp_path, f"{i}.jsonl") for i in range(3)]
    # force one batch per session by shrinking chunks? simpler: 3 sessions fit 1 batch;
    # use --batches 0 is invalid; test --batches 1 with oversized sessions
    for w in work:
        w.chunks = ["x" * 40000]
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: work)
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        main(["--batches", "1"])
    assert mock_reflect.call_count == 1


def test_run_sweep_remembers_chunks_on_success(monkeypatch, tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    import vidura.memory as memory
    memory._reset_breaker_for_tests()
    remembered = []
    monkeypatch.setattr(
        "vidura.sweep.remember_chunks",
        lambda session_path, chunks, *a, **kw: remembered.append((session_path, chunks)),
    )
    batches = [[_work(tmp_path, "a.jsonl")]]
    with patch("vidura.sweep.reflect", return_value=_response()):
        run_sweep(conn, batches)
    assert len(remembered) == 1
    conn.close()


def test_failed_batch_remembers_nothing(monkeypatch, tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    remembered = []
    monkeypatch.setattr(
        "vidura.sweep.remember_chunks",
        lambda session_path, chunks, *a, **kw: remembered.append((session_path, chunks)),
    )
    batches = [[_work(tmp_path, "a.jsonl")]]
    with patch("vidura.sweep.reflect", side_effect=ReflectorError("down")):
        run_sweep(conn, batches)
    assert remembered == []
    conn.close()


def test_batch_request_includes_retrieved_past_friction(monkeypatch, tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    w = _work(tmp_path, "a.jsonl")
    w.error_keys = ["npm error ENEEDAUTH"]
    monkeypatch.setattr(
        "vidura.sweep.search_chunks",
        lambda terms, k=5, exclude_sessions=None: [
            SimpleNamespace(text="[user] npm error ENEEDAUTH from history")
        ],
    )
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        run_sweep(conn, [[w]])
    request = mock_reflect.call_args[0][0]
    assert any("from history" in s for s in request.similar_past_friction)
    conn.close()


def test_batch_request_includes_tool_error_repeats_capped(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    w = _work(tmp_path, "a.jsonl")
    w.tool_error_repeats = {f"tool err {i}": i for i in range(1, 25)}  # 24 distinct
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        run_sweep(conn, [[w]])
    request = mock_reflect.call_args[0][0]
    assert len(request.signals["tool_error_repeats"]) == 20
    conn.close()


def test_batch_request_failure_aborts_only_that_batch(tmp_path):
    """_batch_request itself hits the db (ledger_summary_for_prompt,
    search_chunks) and can raise on its own — it must live INSIDE the
    per-batch try (sweep.py), so a failure there aborts only that
    batch, not the whole sweep. Regression for the boundary bug where
    it sat outside the try."""
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, "a.jsonl")], [_work(tmp_path, "b.jsonl")]]
    call_count = {"n": 0}
    real_batch_request = __import__("vidura.sweep", fromlist=["_batch_request"])._batch_request

    def _flaky_batch_request(conn, batch):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("db locked")
        return real_batch_request(conn, batch)

    with patch("vidura.sweep._batch_request", side_effect=_flaky_batch_request), \
         patch("vidura.sweep.reflect", return_value=_response()):
        stats = run_sweep(conn, batches)
    assert stats["batches_failed"] == 1
    assert stats["batches_run"] == 1
    assert needs_reflection(conn, batches[0][0].path) is True   # first batch never marked
    assert needs_reflection(conn, batches[1][0].path) is False  # second batch still ran
    conn.close()


def test_batch_request_no_error_keys_no_retrieval(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        run_sweep(conn, [[_work(tmp_path, "a.jsonl")]])
    assert mock_reflect.call_args[0][0].similar_past_friction == []
    conn.close()


def test_main_expires_stale_pending_and_logs_to_stderr(tmp_path, monkeypatch, capsys):
    from datetime import datetime, timedelta, timezone

    from vidura.store import ledger_entries, open_db, record_suggestion

    db_path = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db_path))
    conn = open_db(db_path)
    record_suggestion(conn, Suggestion(fix_id="stale-fix", confidence=0.7, evidence=["e"], blunt_summary="s"))
    row_id = ledger_entries(conn)[0]["id"]
    stale_time = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    conn.execute("UPDATE suggestions SET updated_at = ? WHERE id = ?", (stale_time, row_id))
    conn.commit()
    conn.close()

    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "vidura sweep: expired 1 stale pending suggestion(s) (older than 14 days undecided)" in err

    conn = open_db(db_path)
    row = conn.execute("SELECT status FROM suggestions WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "expired"
    conn.close()


def test_main_no_expiry_line_when_nothing_expires(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "expired" not in err


def test_gather_rescan_includes_already_reflected(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    root = tmp_path / "projects"
    root.mkdir()
    seen = _write_friction_session(root, "seen.jsonl")
    mark_reflected(conn, seen)
    assert gather_pending_work(conn, root=root, window_days=30) == []
    work = gather_pending_work(conn, root=root, window_days=30, rescan=True)
    assert [w.path for w in work] == [seen]
    conn.close()


def test_main_logs_character_evolution_on_first_assignment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "vidura sweep: your pet evolved — face -> face" in err


def test_main_logs_character_evolution_on_change(tmp_path, monkeypatch, capsys):
    from vidura.store import open_db as _open_db
    from vidura.store import record_character

    db_path = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db_path))
    conn = _open_db(db_path)
    record_character(
        conn,
        "temple-cat",
        "The Temple Cat — balanced practice",
        "{}",
        assigned_at="2000-01-01T00:00:00+00:00",  # ancient: tenure always satisfied
    )
    conn.close()

    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "vidura sweep: your pet evolved — temple-cat -> face" in err


def test_main_no_evolution_line_when_character_unchanged(tmp_path, monkeypatch, capsys):
    from vidura.store import open_db as _open_db
    from vidura.store import record_character

    db_path = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db_path))
    conn = _open_db(db_path)
    record_character(conn, "face", "The Face — still getting to know you", "{}")
    conn.close()

    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "your pet evolved" not in err


def test_main_prints_memory_status_off_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.delenv("SUPERMEMORY_CC_API_KEY", raising=False)
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "vidura sweep: memory off" in err


def test_main_prints_memory_status_active_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SUPERMEMORY_CC_API_KEY", "sm_test_key")
    import vidura.memory as memory
    memory._reset_breaker_for_tests()
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "vidura sweep: memory active" in err
    memory._reset_breaker_for_tests()


def test_second_concurrent_sweep_skips_cleanly(tmp_path, monkeypatch, capsys):
    """A held sweep-run lockfile makes a second `main()` invocation exit
    0 immediately with one stderr line, touching no work."""
    from vidura.sweep import _sweep_run_lock_path

    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    lock_path = _sweep_run_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(__import__("time").time()), encoding="utf-8")

    called = []
    monkeypatch.setattr(
        "vidura.sweep.gather_pending_work",
        lambda conn, root, window_days, rescan=False: called.append(1) or [],
    )
    exit_code = main([])
    assert exit_code == 0
    assert called == []  # never got past the lock guard
    err = capsys.readouterr().err
    assert "another sweep is running" in err
    lock_path.unlink()


def test_sweep_run_lock_released_after_successful_run(tmp_path, monkeypatch):
    from vidura.sweep import _sweep_run_lock_path

    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    assert not _sweep_run_lock_path().exists()


def test_stale_sweep_run_lock_is_ignored(tmp_path, monkeypatch):
    import os

    from vidura.sweep import SWEEP_RUN_LOCK_STALE_SECONDS, _sweep_run_lock_path

    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    lock_path = _sweep_run_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("stale", encoding="utf-8")
    old = __import__("time").time() - SWEEP_RUN_LOCK_STALE_SECONDS - 60
    os.utime(lock_path, (old, old))

    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: [])
    exit_code = main([])
    assert exit_code == 0
    assert not lock_path.exists()  # a fresh run acquired and then released it (stale lock didn't block it)


def test_sweep_memory_less_end_to_end_green(tmp_path, monkeypatch, capsys):
    """No SUPERMEMORY_CC_API_KEY: the whole sweep flow runs exactly like
    M0 — remember_chunks/search_chunks silently no-op, nothing raises."""
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.delenv("SUPERMEMORY_CC_API_KEY", raising=False)
    work = [_work(tmp_path, "a.jsonl", streaks=3)]
    monkeypatch.setattr("vidura.sweep.gather_pending_work", lambda conn, root, window_days, rescan=False: work)
    with patch("vidura.sweep.reflect", return_value=_response()):
        exit_code = main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "judge-executor-split" in out
