import json
from unittest.mock import patch

from vidura.cli import main
from vidura.contract import CONTRACT_VERSION, ReflectResponse, Suggestion
from vidura.reflect import ReflectorError


def _valid_payload():
    return {
        "contract_version": CONTRACT_VERSION,
        "signals": {},
        "chunks": ["[user] hello"],
        "fix_index": [],
        "ledger": [],
    }


def test_valid_input_prints_suggestions(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(_valid_payload())))
    fake_response = ReflectResponse(
        contract_version=CONTRACT_VERSION,
        suggestions=[Suggestion(fix_id="x", confidence=0.9, evidence=["e"], blunt_summary="s")],
    )
    with patch("vidura.cli.reflect", return_value=fake_response):
        exit_code = main()
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["contract_version"] == CONTRACT_VERSION
    assert len(out["suggestions"]) == 1


def test_contract_version_mismatch_fails_loudly(monkeypatch, capsys):
    payload = _valid_payload()
    payload["contract_version"] = CONTRACT_VERSION + 1
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(payload)))
    exit_code = main()
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "contract_version" in err


def test_invalid_json_on_stdin_fails_loudly(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
    exit_code = main()
    assert exit_code == 2


def test_reflector_error_degrades_to_silence(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(_valid_payload())))
    with patch("vidura.cli.reflect", side_effect=ReflectorError("ollama down")):
        exit_code = main()
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["suggestions"] == []
