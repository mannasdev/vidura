import json

from vidura.state_cli import main
from vidura.store import open_db, record_suggestion
from tests.test_store import _sugg


def test_cli_prints_valid_json_with_all_keys(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    open_db(db).close()

    exit_code = main([])

    assert exit_code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)  # must be the ONLY thing on stdout
    expected_keys = {
        "mood",
        "pending_count",
        "adopted_uncelebrated_ids",
        "streak_rate_7d",
        "streak_rate_baseline",
        "sessions_24h",
    }
    assert set(payload.keys()) == expected_keys
    assert payload["mood"] == "ASLEEP"


def test_cli_reflects_stirring_mood(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    conn = open_db(db)
    record_suggestion(conn, _sugg())
    conn.close()

    exit_code = main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mood"] == "STIRRING"
    assert payload["pending_count"] == 1
