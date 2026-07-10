from vidura.contract import Suggestion
from vidura.ledger_cli import main
from vidura.store import ledger_entries, open_db, record_suggestion


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
