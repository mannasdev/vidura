import json
from pathlib import Path

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


def test_run_sweep_remembers_chunks_on_success(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, "a.jsonl")]]
    with patch("vidura.sweep.reflect", return_value=_response()):
        run_sweep(conn, batches)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1
    conn.close()


def test_failed_batch_remembers_nothing(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    batches = [[_work(tmp_path, "a.jsonl")]]
    with patch("vidura.sweep.reflect", side_effect=ReflectorError("down")):
        run_sweep(conn, batches)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    conn.close()


def test_batch_request_includes_retrieved_past_friction(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    from vidura.memory import remember_chunks
    remember_chunks(conn, "/old/session.jsonl", ["[user] npm error ENEEDAUTH from history"])
    w = _work(tmp_path, "a.jsonl")
    w.error_keys = ["npm error ENEEDAUTH"]
    with patch("vidura.sweep.reflect", return_value=_response()) as mock_reflect:
        run_sweep(conn, [[w]])
    request = mock_reflect.call_args[0][0]
    assert any("from history" in s for s in request.similar_past_friction)
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
