import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from vidura.contract import CONTRACT_VERSION, ReflectResponse, Suggestion
from vidura.report import build_report_request, find_recent_sessions, main, print_report
from vidura.reflect import ReflectorError


def _write_session(path: Path, turns: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")


def _user_turn(text, ts):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _assistant_turn(text, ts, tool_use=False):
    content = [{"type": "text", "text": text}]
    if tool_use:
        content.append({"type": "tool_use", "name": "Read", "input": {}})
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": "claude-sonnet-5", "content": content}}


def test_find_recent_sessions_includes_files_within_window(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    recent = project_dir / "recent.jsonl"
    recent.write_text("{}", encoding="utf-8")
    sessions = find_recent_sessions(root=tmp_path, window_days=30)
    assert recent in sessions


def test_find_recent_sessions_excludes_old_files(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    old = project_dir / "old.jsonl"
    old.write_text("{}", encoding="utf-8")
    old_time = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
    import os
    os.utime(old, (old_time, old_time))
    sessions = find_recent_sessions(root=tmp_path, window_days=30)
    assert old not in sessions


def test_find_recent_sessions_empty_root_returns_empty(tmp_path):
    sessions = find_recent_sessions(root=tmp_path / "does_not_exist", window_days=30)
    assert sessions == []


def test_build_report_request_redacts_secrets(tmp_path):
    session = tmp_path / "session.jsonl"
    ts = "2026-07-01T10:00:00.000Z"
    _write_session(session, [
        _user_turn("here is my key AKIAABCDEFGHIJKLMNOP", ts),
        _user_turn("no not like that", ts),
        _assistant_turn("using a tool now", ts, tool_use=True),
    ])
    request = build_report_request([session])
    combined = " ".join(request.chunks)
    assert "AKIAABCDEFGHIJKLMNOP" not in combined
    assert "[REDACTED]" in combined


def test_build_report_request_only_includes_chunks_with_friction(tmp_path):
    session = tmp_path / "session.jsonl"
    ts = "2026-07-01T10:00:00.000Z"
    _write_session(session, [
        _user_turn("do a simple thing", ts),
        _assistant_turn("done", ts, tool_use=True),
    ])
    request = build_report_request([session])
    assert request.chunks == []
    assert request.signals["sessions_scanned"] == 1


def test_print_report_no_suggestions_message(capsys):
    from vidura.contract import ReflectRequest
    request = ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={"sessions_scanned": 1},
        chunks=[],
        fix_index=[],
        ledger=[],
    )
    with patch("vidura.report.reflect", return_value=ReflectResponse(contract_version=CONTRACT_VERSION, suggestions=[])):
        exit_code = print_report(request)
    assert exit_code == 0
    assert "No suggestions" in capsys.readouterr().out


def test_print_report_degrades_to_silence_on_reflector_error(capsys):
    from vidura.contract import ReflectRequest
    request = ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={"sessions_scanned": 1},
        chunks=[],
        fix_index=[],
        ledger=[],
    )
    with patch("vidura.report.reflect", side_effect=ReflectorError("ollama down")):
        exit_code = print_report(request)
    assert exit_code == 0
    assert "No suggestions" in capsys.readouterr().out


def test_print_report_prints_suggestion_details(capsys):
    from vidura.contract import ReflectRequest
    request = ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={"sessions_scanned": 2},
        chunks=[],
        fix_index=[],
        ledger=[],
    )
    response = ReflectResponse(
        contract_version=CONTRACT_VERSION,
        suggestions=[Suggestion(fix_id="judge-executor-split", confidence=0.85, evidence=["you re-prompted 3x"], blunt_summary="split judge/executor")],
    )
    with patch("vidura.report.reflect", return_value=response):
        print_report(request)
    out = capsys.readouterr().out
    assert "judge-executor-split" in out
    assert "split judge/executor" in out
    assert "you re-prompted 3x" in out


def test_main_no_sessions_found(monkeypatch, capsys):
    monkeypatch.setattr("vidura.report.find_recent_sessions", lambda: [])
    exit_code = main()
    assert exit_code == 0
    assert "No Claude Code sessions found" in capsys.readouterr().out


def test_build_report_request_prioritizes_friction_dense_chunks(tmp_path):
    ts = "2026-07-01T10:00:00.000Z"
    # session A: one streak turn pair, low user-turn density in its chunk
    session_a = tmp_path / "a.jsonl"
    _write_session(session_a, [
        _user_turn("low density " + "x" * 30000, ts),
        _user_turn("second", ts),
        _assistant_turn("done", ts, tool_use=True),
    ])
    # session B: many consecutive user turns — high density
    session_b = tmp_path / "b.jsonl"
    _write_session(session_b, [
        _user_turn("try again " + "y" * 30000, ts),
        _user_turn("no, not like that", ts),
        _user_turn("still wrong", ts),
        _user_turn("one more time", ts),
        _assistant_turn("ok", ts, tool_use=True),
    ])
    request = build_report_request([session_a, session_b])
    # both sessions produce oversized chunks; budget forces a cut, and the
    # user-turn-dense chunk (session B's tail) must survive it
    assert any("not like that" in c for c in request.chunks)
