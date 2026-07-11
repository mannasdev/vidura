import json
from pathlib import Path

import pytest

from vidura.ingest import parse_session


def _write_jsonl(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_parses_user_text_turn(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert len(turns) == 1
    assert turns[0].type == "user"
    assert turns[0].text == "hello"
    assert turns[0].tool_use is False


def test_parses_user_string_content(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": "hello as a plain string"},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].text == "hello as a plain string"


def test_parses_assistant_tool_use_turn(tmp_path):
    line = json.dumps({
        "type": "assistant",
        "timestamp": "2026-07-01T10:00:05.000Z",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [
                {"type": "text", "text": "I'll check that file."},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "x.py"}},
            ],
        },
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].type == "assistant"
    assert turns[0].tool_use is True
    assert "I'll check that file." in turns[0].text
    assert turns[0].model == "claude-sonnet-5"


def test_skips_malformed_line_and_continues(tmp_path, capsys):
    good_line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "first"}]},
    })
    bad_line = "{not valid json"
    good_line_2 = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:01:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "second"}]},
    })
    path = _write_jsonl(tmp_path, [good_line, bad_line, good_line_2])
    turns = list(parse_session(path))
    assert [t.text for t in turns] == ["first", "second"]
    captured = capsys.readouterr()
    assert "skipping malformed line 2" in captured.err


def test_skips_non_user_assistant_record_types(tmp_path):
    mode_line = json.dumps({"type": "mode", "sessionId": "x", "mode": "default"})
    user_line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    })
    path = _write_jsonl(tmp_path, [mode_line, user_line])
    turns = list(parse_session(path))
    assert len(turns) == 1
    assert turns[0].text == "hi"


def test_skips_blank_lines(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    })
    path = _write_jsonl(tmp_path, [line, "", "   ", line])
    turns = list(parse_session(path))
    assert len(turns) == 2


def test_tool_result_only_turn_flagged(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ls output here"}]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].is_tool_result is True
    assert turns[0].text == "ls output here"


def test_human_text_turn_not_flagged_as_tool_result(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "real human prompt"}]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].is_tool_result is False


def test_mixed_text_and_tool_result_counts_as_human(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "output"},
            {"type": "text", "text": "and my follow-up question"},
        ]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].is_tool_result is False


def test_tool_result_list_shaped_content_extracted(tmp_path):
    """Claude Code sometimes delivers tool_result content as a list of
    blocks (mirroring assistant message content) rather than a plain
    string — a naive isinstance(..., str) check silently dropped this
    shape entirely, hiding tracebacks/errors that arrived this way from
    both chunking and signal extraction."""
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": [
                {"type": "text", "text": "Traceback (most recent call last):\nError: boom"},
            ]},
        ]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].is_tool_result is True
    assert "Traceback (most recent call last):" in turns[0].text
    assert "Error: boom" in turns[0].text


def test_tool_result_list_shaped_multiple_text_blocks_concatenated(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": [
                {"type": "text", "text": "first part"},
                {"type": "text", "text": "second part"},
            ]},
        ]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert "first part" in turns[0].text
    assert "second part" in turns[0].text


def test_assistant_tool_use_extracts_tool_names(tmp_path):
    line = json.dumps({
        "type": "assistant",
        "timestamp": "2026-07-01T10:00:05.000Z",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [
                {"type": "text", "text": "checking a file, then running a tool"},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "x.py"}},
                {"type": "tool_use", "name": "mcp__playwright__click", "input": {}},
            ],
        },
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].tool_names == ["Read", "mcp__playwright__click"]


def test_no_tool_use_yields_empty_tool_names(tmp_path):
    line = json.dumps({
        "type": "assistant",
        "timestamp": "2026-07-01T10:00:05.000Z",
        "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "just talk"}]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].tool_names == []


def test_user_turn_has_empty_tool_names(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": "plain string content"},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].tool_names == []


def test_tool_result_list_shaped_ignores_non_text_blocks(tmp_path):
    line = json.dumps({
        "type": "user",
        "timestamp": "2026-07-01T10:00:00.000Z",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": [
                {"type": "image", "source": {"data": "base64stuff"}},
                {"type": "text", "text": "the actual text"},
            ]},
        ]},
    })
    path = _write_jsonl(tmp_path, [line])
    turns = list(parse_session(path))
    assert turns[0].text == "the actual text"
    assert "base64stuff" not in turns[0].text
