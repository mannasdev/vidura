import json
from unittest.mock import MagicMock, patch

import pytest

from vidura.contract import CONTRACT_VERSION, ReflectRequest
from vidura.reflect import ReflectorError, build_prompt, parse_suggestions, reflect


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


def test_parse_suggestions_caps_at_three():
    raw = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.9, "evidence": ["q"], "blunt_summary": "s"}
        for _ in range(5)
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 3


def test_reflect_takes_only_request_param():
    """Deletion debris cleanup: all 3 real call sites (cli.py, report.py,
    sweep.py) pass a bare request — the model/timeout_seconds pass-through
    params were unused, dropped."""
    import inspect

    assert list(inspect.signature(reflect).parameters) == ["request"]


def test_reflect_returns_suggestions_from_mocked_claude_cli():
    # Evidence must quote the chunk: the live path verifies against request.chunks.
    mock_response = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.85, "evidence": ["no not like that"], "blunt_summary": "split judge/executor"}
    ])
    with patch("vidura.reflect.call_claude_cli", return_value=mock_response):
        response = reflect(_request())
    assert response.contract_version == CONTRACT_VERSION
    assert len(response.suggestions) == 1


def test_reflect_raises_reflector_error_when_claude_cli_call_fails():
    with patch("vidura.reflect.call_claude_cli", side_effect=ReflectorError("claude CLI not found on PATH")):
        with pytest.raises(ReflectorError):
            reflect(_request())


def test_call_claude_cli_missing_binary_raises():
    from vidura.reflect import call_claude_cli
    with patch("vidura.reflect.shutil.which", return_value=None):
        with pytest.raises(ReflectorError):
            call_claude_cli("prompt")


def test_call_claude_cli_nonzero_exit_raises():
    from vidura.reflect import call_claude_cli
    proc = MagicMock(returncode=1, stdout="", stderr="auth expired")
    with patch("vidura.reflect.shutil.which", return_value="/usr/local/bin/claude"), \
         patch("vidura.reflect.subprocess.run", return_value=proc):
        with pytest.raises(ReflectorError):
            call_claude_cli("prompt")


def test_call_claude_cli_extracts_result_from_envelope():
    from vidura.reflect import call_claude_cli
    envelope = json.dumps({"result": '{"suggestions": []}', "session_id": "x"})
    proc = MagicMock(returncode=0, stdout=envelope, stderr="")
    with patch("vidura.reflect.shutil.which", return_value="/usr/local/bin/claude"), \
         patch("vidura.reflect.subprocess.run", return_value=proc):
        assert call_claude_cli("prompt") == '{"suggestions": []}'


def test_call_claude_cli_restricts_tools_and_turns():
    from vidura.reflect import call_claude_cli
    envelope = json.dumps({"result": '{"suggestions": []}', "session_id": "x"})
    proc = MagicMock(returncode=0, stdout=envelope, stderr="")
    with patch("vidura.reflect.shutil.which", return_value="/usr/local/bin/claude"), \
         patch("vidura.reflect.subprocess.run", return_value=proc) as mock_run:
        call_claude_cli("prompt")
    argv = mock_run.call_args[0][0]
    assert "--max-turns" in argv
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert "--disallowedTools" in argv
    assert argv[argv.index("--disallowedTools") + 1] == "*"


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


def test_build_prompt_omits_past_friction_when_empty():
    prompt = build_prompt(_request())
    assert "<similar_past_friction>" not in prompt


# --- Fix 5: a hallucinated fix_id must be treated as novel ---


def test_parse_suggestions_hallucinated_fix_id_becomes_novel():
    raw = json.dumps([
        {"fix_id": "made-up-fix", "confidence": 0.85, "evidence": ["quote"], "blunt_summary": "phantom"}
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].novel is True
    # The model's id string is kept so context isn't lost.
    assert suggestions[0].fix_id == "made-up-fix"


def test_parse_suggestions_hallucinated_fix_id_gets_novel_floor():
    # 0.75 clears the known-fix default floor but not the 0.8 novel floor.
    raw = json.dumps([
        {"fix_id": "made-up-fix", "confidence": 0.75, "evidence": ["quote"], "blunt_summary": "phantom"}
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert suggestions == []


def test_parse_suggestions_valid_fix_id_not_marked_novel():
    raw = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.75, "evidence": ["quote"], "blunt_summary": "real"}
    ])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].novel is False
    assert suggestions[0].fix_id == "judge-executor-split"


# --- Fix 6: evidence quotes are verified against the chunks ---

CHUNK = "[user] please stop rewriting the whole file every time I ask for a small change"


def _suggestion_raw(evidence):
    return json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.9, "evidence": evidence, "blunt_summary": "s"}
    ])


def test_verification_exact_quote_passes():
    raw = _suggestion_raw(["stop rewriting the whole file"])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7}, chunks=[CHUNK])
    assert len(suggestions) == 1
    assert suggestions[0].evidence == ["stop rewriting the whole file"]


def test_verification_whitespace_mangled_quote_passes():
    raw = _suggestion_raw(["stop  rewriting\n   the whole\tfile"])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7}, chunks=[CHUNK])
    assert len(suggestions) == 1


def test_verification_shingle_overlap_tolerates_light_paraphrase():
    # 8 words -> 4 shingles; dropping "please" leaves 3 of 4 intact (75% >= 70%).
    raw = _suggestion_raw(["stop rewriting the whole file every time I"])
    chunk = "[user] stop rewriting the whole file every time I ask"
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7}, chunks=[chunk])
    assert len(suggestions) == 1


def test_verification_drops_fabricated_quote_keeps_real_one():
    raw = _suggestion_raw(["you deleted the production database", "stop rewriting the whole file"])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7}, chunks=[CHUNK])
    assert len(suggestions) == 1
    assert suggestions[0].evidence == ["stop rewriting the whole file"]


def test_verification_drops_suggestion_when_all_evidence_fabricated():
    raw = _suggestion_raw(["you deleted the production database"])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7}, chunks=[CHUNK])
    assert suggestions == []


def test_verification_drops_non_string_evidence_items():
    raw = _suggestion_raw([42, {"quote": "nested"}, "stop rewriting the whole file"])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7}, chunks=[CHUNK])
    assert len(suggestions) == 1
    assert suggestions[0].evidence == ["stop rewriting the whole file"]


def test_verification_skipped_when_chunks_none():
    raw = _suggestion_raw(["you deleted the production database"])
    suggestions = parse_suggestions(raw, {"judge-executor-split": 0.7})
    assert len(suggestions) == 1
    assert suggestions[0].evidence == ["you deleted the production database"]


def test_reflect_verifies_evidence_against_request_chunks():
    # The live path must always verify: fabricated evidence never reaches callers.
    mock_response = json.dumps([
        {"fix_id": "judge-executor-split", "confidence": 0.9, "evidence": ["you deleted the production database"], "blunt_summary": "fake"}
    ])
    with patch("vidura.reflect.call_claude_cli", return_value=mock_response):
        response = reflect(_request())
    assert response.suggestions == []


def test_build_prompt_renders_past_friction_between_sessions_and_fixes():
    req = _request()
    req.similar_past_friction = ["[user] we saw this ENEEDAUTH before"]
    prompt = build_prompt(req)
    assert prompt.index("<recent_sessions>") < prompt.index("<similar_past_friction>") < prompt.index("<fix_index>")
    assert "ENEEDAUTH before" in prompt
    assert "background context — do not quote as evidence" in prompt
