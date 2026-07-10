import json

from vidura.contract import Suggestion
from vidura.ledger_cli import main
from vidura.store import ledger_entries, open_db, record_suggestion, set_status


def _seed(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    conn = open_db(db)
    record_suggestion(conn, Suggestion(fix_id="judge-executor-split", confidence=0.8, evidence=["q"], blunt_summary="split it"))
    row_id = ledger_entries(conn)[0]["id"]
    conn.close()
    return db, row_id


def test_list_shows_entries(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "judge-executor-split" in out
    assert "pending" in out


def test_accept_updates_status(tmp_path, monkeypatch, capsys):
    db, row_id = _seed(tmp_path, monkeypatch)
    assert main(["accept", str(row_id)]) == 0
    conn = open_db(db)
    assert ledger_entries(conn)[0]["status"] == "accepted"
    conn.close()


def test_dismiss_updates_status(tmp_path, monkeypatch):
    db, row_id = _seed(tmp_path, monkeypatch)
    assert main(["dismiss", str(row_id)]) == 0
    conn = open_db(db)
    assert ledger_entries(conn)[0]["status"] == "dismissed"
    conn.close()


def test_unknown_id_exits_nonzero(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    assert main(["accept", "999"]) == 1
    assert "no suggestion with id" in capsys.readouterr().err


def test_empty_ledger_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    assert main(["list"]) == 0
    assert "empty" in capsys.readouterr().out.lower()


def test_list_strips_control_chars_from_summary(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    conn = open_db(db)
    record_suggestion(
        conn,
        Suggestion(
            fix_id="repeated-error-loop",
            confidence=0.9,
            evidence=["q"],
            blunt_summary="\x1b[31msummary with escape\x1b[0m",
        ),
    )
    conn.close()
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "summary with escape" in out


def test_list_json_prints_only_json_array(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    assert main(["list", "--json"]) == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert isinstance(rows, list)
    assert len(rows) == 1


def test_list_json_fields(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    assert main(["list", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    for field in (
        "id",
        "fix_id",
        "status",
        "confidence",
        "occurrences",
        "blunt_summary",
        "evidence",
        "novel",
        "updated_at",
        "has_action",
        "action_label",
    ):
        assert field in row
    assert row["fix_id"] == "judge-executor-split"
    assert row["status"] == "pending"
    assert isinstance(row["evidence"], list)
    assert row["evidence"] == ["q"]


def test_list_json_has_action_true_with_label(tmp_path, monkeypatch, capsys):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    conn = open_db(db)
    record_suggestion(
        conn,
        Suggestion(fix_id="spec-before-code", confidence=0.8, evidence=["q"], blunt_summary="s"),
    )
    conn.close()
    assert main(["list", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["has_action"] is True
    assert row["action_label"] == "Copy /office-hours"


def test_list_json_has_action_false_for_inform_only_fix(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)  # judge-executor-split has no action
    assert main(["list", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["has_action"] is False
    assert row["action_label"] is None


def test_list_json_empty_ledger_prints_empty_array(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    assert main(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_list_without_json_flag_prints_human_output_unchanged(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "[" in out and "judge-executor-split" in out
    # Not valid JSON — human-readable path is untouched.
    try:
        json.loads(out)
        parsed_as_json = True
    except json.JSONDecodeError:
        parsed_as_json = False
    assert not parsed_as_json


def test_celebrate_marks_celebrated(tmp_path, monkeypatch, capsys):
    db, row_id = _seed(tmp_path, monkeypatch)
    conn = open_db(db)
    set_status(conn, row_id, "adopted")
    conn.close()
    assert main(["celebrate", str(row_id)]) == 0
    conn = open_db(db)
    row = conn.execute("SELECT celebrated FROM suggestions WHERE id = ?", (row_id,)).fetchone()
    conn.close()
    assert row["celebrated"] == 1
    assert "celebrat" in capsys.readouterr().out.lower()


def test_celebrate_unknown_id_exits_nonzero(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch)
    assert main(["celebrate", "999"]) == 1
    assert "no suggestion with id" in capsys.readouterr().err
