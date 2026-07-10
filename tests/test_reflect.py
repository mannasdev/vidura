import json
from unittest.mock import MagicMock, patch

import pytest

from vidura.contract import CONTRACT_VERSION, ReflectRequest
from vidura.reflect import ReflectorError, build_prompt, call_ollama, parse_suggestions, reflect


def _request(chunks=None, fix_index=None):
    return ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={"sessions_scanned": 1},
        chunks=chunks or ["[user] do the thing\n[user] no not like that"],
        fix_index=fix_index or [{"id": "judge-executor-split", "confidence_floor": 0.7}],
        ledger=[],
    )


def test_build_prompt_contains_all_sections():
    prompt = build_prompt(_request())
    assert "<signals>" in prompt
    assert "<recent_sessions>" in prompt
    assert "<fix_index>" in prompt
    assert "<ledger>" in prompt
    assert "do the thing" in prompt


def test_parse_suggestions_keeps_suggestion_above_floor():
    raw = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.8, "evidence": ["quote"], "blunt_summary": "you re-prompted a lot"}
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].fix_id == "judge-executor-split"


def test_parse_suggestions_drops_suggestion_below_floor():
    raw = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.5, "evidence": ["quote"], "blunt_summary": "maybe"}
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert suggestions == []


def test_parse_suggestions_marks_novel_when_no_fix_id():
    raw = json.dumps([
        {"fix_id": None, "confidence": 0.9, "evidence": ["quote"], "blunt_summary": "new pattern"}
    ])
    suggestions = parse_suggestions(raw, {})
    assert suggestions[0].novel is True
    assert suggestions[0].fix_id == "novel"


def test_parse_suggestions_raises_on_invalid_json():
    with pytest.raises(ReflectorError):
        parse_suggestions("not json at all", {})


def test_parse_suggestions_raises_on_non_array():
    with pytest.raises(ReflectorError):
        parse_suggestions(json.dumps({"not": "an array"}), {})


def test_reflect_returns_suggestions_from_mocked_ollama():
    mock_response = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.85, "evidence": ["you re-prompted 3x"], "blunt_summary": "split judge/executor"}
    ])
    with patch("vidura.reflect.call_ollama", return_value=mock_response):
        response = reflect(_request())
    assert response.contract_version == CONTRACT_VERSION
    assert len(response.suggestions) == 1


def test_reflect_raises_reflector_error_when_ollama_call_fails():
    with patch("vidura.reflect.call_ollama", side_effect=ReflectorError("unreachable")):
        with pytest.raises(ReflectorError):
            reflect(_request())


def _mock_urlopen(body_bytes):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body_bytes
    cm.__exit__.return_value = False
    return cm


def test_call_ollama_non_json_body_raises_reflector_error():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(b"<html>502 Bad Gateway</html>")):
        with pytest.raises(ReflectorError):
            call_ollama("prompt")


def test_call_ollama_non_dict_body_raises_reflector_error():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(json.dumps(["a", "b"]).encode("utf-8"))):
        with pytest.raises(ReflectorError):
            call_ollama("prompt")


def test_parse_suggestions_skips_non_dict_items():
    raw = json.dumps([
        "just a string",
        {"fix_id": "judge-executor-split", "confidence": 0.9, "evidence": ["quote"], "blunt_summary": "ok"},
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].fix_id == "judge-executor-split"


def test_parse_suggestions_skips_non_numeric_confidence():
    raw = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": "high", "evidence": ["quote"], "blunt_summary": "bad"},
        {"fix_id": None, "confidence": None, "evidence": ["quote"], "blunt_summary": "bad2"},
        {"fix_id": "judge-executor-split", "confidence": 0.9, "evidence": ["quote"], "blunt_summary": "good"},
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].blunt_summary == "good"


def test_parse_suggestions_handles_markdown_fenced_json():
    raw = "```json\n" + json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.9, "evidence": ["quote"], "blunt_summary": "fenced"}
    ]) + "\n```"
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].blunt_summary == "fenced"


def test_parse_suggestions_unwraps_suggestions_object():
    raw = json.dumps({
        "suggestions": [
            {"fix_id": "judge-executor-split", "confidence": 0.85, "evidence": ["quote"], "blunt_summary": "split it"}
        ]
    })
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].fix_id == "judge-executor-split"


def test_parse_suggestions_object_without_suggestions_key_raises():
    with pytest.raises(ReflectorError):
        parse_suggestions(json.dumps({"not": "an array"}), {})


def test_build_prompt_ends_with_closing_instruction():
    prompt = build_prompt(_request())
    assert prompt.rstrip().endswith('empty array if nothing clears the bar.')
    assert prompt.index("<recent_sessions>") < prompt.index("Remember: you are Vidura")
