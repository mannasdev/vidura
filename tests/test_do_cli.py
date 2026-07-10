from unittest.mock import patch

from vidura.contract import Suggestion
from vidura.do_cli import main
from vidura.store import ledger_entries, open_db, record_suggestion, set_status


def _seed(tmp_path, monkeypatch, fix_id="judge-executor-split", status="pending"):
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("VIDURA_DB_PATH", str(db))
    conn = open_db(db)
    record_suggestion(
        conn, Suggestion(fix_id=fix_id, confidence=0.8, evidence=["q"], blunt_summary="summary")
    )
    row_id = ledger_entries(conn)[0]["id"]
    if status != "pending":
        set_status(conn, row_id, status)
    conn.close()
    return db, row_id


def test_pending_suggestion_refused(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch, status="pending")
    rc = main(["1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "accept it first: vidura-ledger accept" in err


def test_accepted_inform_fix_explains_no_action(tmp_path, monkeypatch, capsys):
    _seed(tmp_path, monkeypatch, fix_id="judge-executor-split", status="accepted")
    rc = main(["1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no executable action for this fix — remedy:" in err


def test_accepted_copy_action_succeeds(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="spec-before-code", status="accepted")
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        rc = main(["1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "done" in out.lower()


def test_dry_run_prints_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="spec-before-code", status="accepted")
    with patch("vidura.executor.subprocess.run") as mock_run:
        rc = main(["1", "--dry-run"])
        mock_run.assert_not_called()
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()


def test_declined_confirmation_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="missing-claude-md", status="accepted")
    with patch("vidura.do_cli._tty_confirm", return_value=False):
        rc = main(["1"])
    assert rc == 2


def test_unknown_id_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / "db.sqlite"))
    rc = main(["999"])
    assert rc == 1
    assert "no suggestion with id" in capsys.readouterr().err


def test_failed_execution_exits_three(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="github-context-by-paste", status="accepted")
    with patch("vidura.do_cli._tty_confirm", return_value=True):
        with patch("vidura.executor.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b"brew: command not found\n"
            rc = main(["1"])
    assert rc == 3
    out = capsys.readouterr().out
    assert "failed" in out.lower()


def test_yes_flag_executes_copy_without_confirm_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="spec-before-code", status="accepted")
    with patch("vidura.do_cli._tty_confirm") as mock_confirm:
        with patch("vidura.executor.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            rc = main(["1", "--yes"])
        mock_confirm.assert_not_called()
    assert rc == 0
    assert "done" in capsys.readouterr().out.lower()


def test_yes_flag_bypasses_confirm_for_tier2_write(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="missing-claude-md", status="accepted")
    with patch("vidura.do_cli._tty_confirm") as mock_confirm:
        rc = main(["1", "--yes"])
        mock_confirm.assert_not_called()
    assert rc == 0
    assert (tmp_path / "CLAUDE.md").exists()


def test_yes_plus_kill_switch_still_refuses_tier2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VIDURA_EXECUTION", "off")
    _seed(tmp_path, monkeypatch, fix_id="missing-claude-md", status="accepted")
    rc = main(["1", "--yes"])
    assert rc == 1
    assert "disabled" in capsys.readouterr().err.lower()


def test_dry_run_wins_over_yes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path, monkeypatch, fix_id="spec-before-code", status="accepted")
    with patch("vidura.executor.subprocess.run") as mock_run:
        rc = main(["1", "--yes", "--dry-run"])
        mock_run.assert_not_called()
    assert rc == 0
    assert "dry-run" in capsys.readouterr().out.lower()


def test_yes_flag_recorded_as_normal_done_audit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    db, row_id = _seed(tmp_path, monkeypatch, fix_id="spec-before-code", status="accepted")
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        rc = main([str(row_id), "--yes"])
    assert rc == 0
    conn = open_db(db)
    from vidura.store import executions_for

    audits = executions_for(conn, row_id)
    conn.close()
    assert len(audits) == 1
    assert audits[0]["status"] == "done"
