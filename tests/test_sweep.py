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
    return SessionWork(path=p, chunks=[f"[user] chunk of {name}"], streak_count=streaks)


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
