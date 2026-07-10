import json
from datetime import datetime, timezone

from vidura.state_cli import main
from vidura.store import open_db, record_character, record_suggestion
from tests.test_store import _sugg

EXPECTED_KEYS = {
    "mood",
    "pending_count",
    "adopted_uncelebrated_ids",
    "streak_rate_7d",
    "streak_rate_baseline",
    "sessions_24h",
    "character",
    "character_since",
    "character_reason",
}


def test_cli_prints_valid_json_with_all_keys(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    open_db(db).close()

    exit_code = main([])

    assert exit_code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)  # must be the ONLY thing on stdout
    assert set(payload.keys()) == EXPECTED_KEYS
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


def test_cli_defaults_character_when_no_history(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    open_db(db).close()

    before = datetime.now(timezone.utc)
    exit_code = main([])
    after = datetime.now(timezone.utc)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["character"] == "face"
    assert payload["character_reason"] == "still getting to know you"
    # character_since must be a real ISO-8601 timestamp, not a sentinel
    since = datetime.fromisoformat(payload["character_since"])
    assert before <= since <= after


def test_cli_reflects_recorded_character(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    conn = open_db(db)
    record_character(
        conn,
        "founder",
        "The Founder — 41 sessions and 52 hours in 14 days",
        json.dumps({"n_sessions": 41}),
        assigned_at="2026-07-01T00:00:00+00:00",
    )
    conn.close()

    exit_code = main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["character"] == "founder"
    assert payload["character_since"] == "2026-07-01T00:00:00+00:00"
    assert payload["character_reason"] == "The Founder — 41 sessions and 52 hours in 14 days"
