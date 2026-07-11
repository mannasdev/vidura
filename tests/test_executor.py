"""Tests for vidura.executor — tier-dispatched action execution.

All subprocess calls are mocked (no real pbcopy/brew/etc touches CI),
confirm is always a fake callable (tests never touch a TTY), and any
file writes land in tmp_path via monkeypatch.chdir.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

import subprocess

from vidura.executor import (
    CwdGuardError,
    ExecutionDeclined,
    ExecutionError,
    execute_action,
    execution_enabled,
)
from vidura.fix_index import Fix, FixAction
from vidura.store import executions_for, open_db


def _suggestion_row(conn, fix_id="missing-claude-md"):
    from vidura.contract import Suggestion
    from vidura.store import ledger_entries, record_suggestion, set_status

    record_suggestion(
        conn,
        Suggestion(fix_id=fix_id, confidence=0.8, evidence=["q"], blunt_summary="summary"),
    )
    row = ledger_entries(conn)[0]
    set_status(conn, row["id"], "accepted")
    return ledger_entries(conn)[0]


def _always_yes(prompt: str) -> bool:
    return True


def _always_no(prompt: str) -> bool:
    return False


def test_execution_enabled_default_true(monkeypatch):
    monkeypatch.delenv("VIDURA_EXECUTION", raising=False)
    assert execution_enabled() is True


def test_execution_enabled_false_when_off(monkeypatch):
    monkeypatch.setenv("VIDURA_EXECUTION", "off")
    assert execution_enabled() is False


def test_copy_pipes_payload_to_pbcopy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "spec-before-code")
    fix = Fix(
        id="spec-before-code",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=1, label="Copy /office-hours", payload="/office-hours"),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        status = execute_action(conn, row, fix, confirm=_always_no)
    assert status == "done"
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["pbcopy"]
    assert kwargs["input"] == b"/office-hours"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["tier"] == 1
    conn.close()


def test_write_appends_once_after_confirm_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )
    status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    target = tmp_path / "CLAUDE.md"
    assert target.exists()
    assert target.read_text() == "# Project\n"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["tier"] == 2


def test_write_confirm_false_declines_and_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )
    with pytest.raises(ExecutionDeclined):
        execute_action(conn, row, fix, confirm=_always_no)
    assert not (tmp_path / "CLAUDE.md").exists()
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "declined"


def test_run_passes_argv_list_no_shell_and_records_exit_code(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Installing gh...\n"
        mock_run.return_value.stderr = ""
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    args, kwargs = mock_run.call_args
    assert args[0] == ["brew", "install", "gh"]
    assert "shell" not in kwargs or kwargs["shell"] is False
    assert kwargs["timeout"] == 300
    assert kwargs["capture_output"] is True
    rows = executions_for(conn, row["id"])
    assert rows[0]["exit_code"] == 0
    assert rows[0]["status"] == "done"


def test_run_nonzero_exit_recorded_as_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "brew: command not found\n"
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "failed"
    rows = executions_for(conn, row["id"])
    assert rows[0]["exit_code"] == 1
    assert rows[0]["status"] == "failed"
    assert "brew: command not found" in rows[0]["output_head"]


def test_run_confirm_false_declines_and_never_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        with pytest.raises(ExecutionDeclined):
            execute_action(conn, row, fix, confirm=_always_no)
        mock_run.assert_not_called()
    rows = executions_for(conn, row["id"])
    assert rows[0]["status"] == "declined"


def test_kill_switch_blocks_tier_two_and_three(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    monkeypatch.setenv("VIDURA_EXECUTION", "off")
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )
    with pytest.raises(PermissionError):
        execute_action(conn, row, fix, confirm=_always_yes)
    assert not (tmp_path / "CLAUDE.md").exists()
    assert executions_for(conn, row["id"]) == []


def test_kill_switch_does_not_block_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    monkeypatch.setenv("VIDURA_EXECUTION", "off")
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "spec-before-code")
    fix = Fix(
        id="spec-before-code",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=1, label="Copy /office-hours", payload="/office-hours"),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        status = execute_action(conn, row, fix, confirm=_always_no)
    assert status == "done"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1


def test_dry_run_records_nothing_and_touches_nothing_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )
    status = execute_action(conn, row, fix, confirm=_always_yes, dry_run=True)
    assert status == "dry-run"
    assert not (tmp_path / "CLAUDE.md").exists()
    assert executions_for(conn, row["id"]) == []


def test_dry_run_records_nothing_run_tier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        status = execute_action(conn, row, fix, confirm=_always_yes, dry_run=True)
        mock_run.assert_not_called()
    assert status == "dry-run"
    assert executions_for(conn, row["id"]) == []


def test_write_rejects_absolute_path_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(
            tier=2, label="Write", payload="pwned\n", target_file="/etc/hosts"
        ),
    )
    with pytest.raises(ValueError):
        execute_action(conn, row, fix, confirm=_always_yes)
    assert not Path("/etc/hosts").read_text().startswith("pwned")
    assert executions_for(conn, row["id"]) == []


def test_write_rejects_dotdot_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(
            tier=2,
            label="Write",
            payload="pwned\n",
            target_file="../escape.md",
        ),
    )
    with pytest.raises(ValueError):
        execute_action(conn, row, fix, confirm=_always_yes)
    assert not (tmp_path.parent / "escape.md").exists()
    assert executions_for(conn, row["id"]) == []


def test_decode_error_still_records_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b"\xff\xfe invalid utf8 \x80"
        mock_run.return_value.stderr = b""
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"


def test_none_action_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "judge-executor-split")
    fix = Fix(
        id="judge-executor-split",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=None,
    )
    with pytest.raises(ValueError, match="fix has no executable action"):
        execute_action(conn, row, fix, confirm=_always_yes)


def test_dry_run_works_under_kill_switch(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    monkeypatch.setenv("VIDURA_EXECUTION", "off")
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )
    status = execute_action(conn, row, fix, confirm=_always_yes, dry_run=True)
    assert status == "dry-run"
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_copy_records_failed_status_on_nonzero_pbcopy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "spec-before-code")
    fix = Fix(
        id="spec-before-code",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=1, label="Copy /office-hours", payload="/office-hours"),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        status = execute_action(conn, row, fix, confirm=_always_no)
    assert status == "failed"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["exit_code"] == 1


def test_dry_run_copy_does_not_touch_clipboard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "spec-before-code")
    fix = Fix(
        id="spec-before-code",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=1, label="Copy /office-hours", payload="/office-hours"),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        status = execute_action(conn, row, fix, confirm=_always_yes, dry_run=True)
        mock_run.assert_not_called()
    assert status == "dry-run"
    assert executions_for(conn, row["id"]) == []


# ---------------------------------------------------------------------------
# audit-on-error/timeout (post-confirm subprocess/filesystem failures)
# ---------------------------------------------------------------------------


def test_run_timeout_records_audit_and_raises_execution_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="brew", timeout=300)):
        with pytest.raises(ExecutionError):
            execute_action(conn, row, fix, confirm=_always_yes)
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "timeout"


def test_run_missing_binary_records_audit_and_raises_execution_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run", side_effect=FileNotFoundError("no such file: brew")):
        with pytest.raises(ExecutionError):
            execute_action(conn, row, fix, confirm=_always_yes)
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "error"


def test_write_filesystem_error_records_audit_and_raises_execution_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    fix = Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )
    with patch("pathlib.Path.open", side_effect=OSError("disk full")):
        with pytest.raises(ExecutionError):
            execute_action(conn, row, fix, confirm=_always_yes)
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "error"


# ---------------------------------------------------------------------------
# cwd guard (WRITE/RUN refuse outside a git repo, at /, or at $HOME)
# ---------------------------------------------------------------------------


def _write_fix():
    return Fix(
        id="missing-claude-md",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=2, label="Write CLAUDE.md", payload="# Project\n", target_file="CLAUDE.md"),
    )


def test_write_refuses_outside_git_repo(tmp_path, monkeypatch):
    """A tmp dir with no .git anywhere in its ancestry refuses WRITE —
    this is the pet-launched-from-Finder scenario (cwd is / or $HOME),
    generalized to any non-repo cwd."""
    monkeypatch.chdir(tmp_path)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    with pytest.raises(CwdGuardError, match="not inside a git repo"):
        execute_action(conn, row, _write_fix(), confirm=_always_yes)
    assert not (tmp_path / "CLAUDE.md").exists()
    assert executions_for(conn, row["id"]) == []  # refused before any audit point


def test_write_allowed_inside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    status = execute_action(conn, row, _write_fix(), confirm=_always_yes)
    assert status == "done"
    assert (tmp_path / "CLAUDE.md").exists()


def test_write_allowed_in_subdirectory_of_git_repo(tmp_path, monkeypatch):
    """The .git marker can live in a PARENT of cwd, not just cwd itself
    — a normal working directory is often a subdirectory of the repo
    root."""
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "src" / "nested"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    conn = open_db(subdir / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    status = execute_action(conn, row, _write_fix(), confirm=_always_yes)
    assert status == "done"
    assert (subdir / "CLAUDE.md").exists()


def test_run_refuses_outside_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "github-context-by-paste")
    fix = Fix(
        id="github-context-by-paste",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=3, label="Install gh", payload="", argv=["brew", "install", "gh"]),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        with pytest.raises(CwdGuardError):
            execute_action(conn, row, fix, confirm=_always_yes)
        mock_run.assert_not_called()
    assert executions_for(conn, row["id"]) == []


def test_dry_run_bypasses_cwd_guard(tmp_path, monkeypatch, capsys):
    """dry-run never touches the filesystem or runs anything, so it's
    exempt from the cwd guard — a user can preview an action's exact
    content/argv from anywhere, same as before this change."""
    monkeypatch.chdir(tmp_path)  # no .git anywhere
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "missing-claude-md")
    status = execute_action(conn, row, _write_fix(), confirm=_always_yes, dry_run=True)
    assert status == "dry-run"
    assert not (tmp_path / "CLAUDE.md").exists()


def test_copy_bypasses_cwd_guard(tmp_path, monkeypatch):
    """COPY (tier 1) never touches the filesystem or runs a command
    from cwd — it's unaffected by the guard even outside a git repo."""
    monkeypatch.chdir(tmp_path)  # no .git anywhere
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "spec-before-code")
    fix = Fix(
        id="spec-before-code",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(tier=1, label="Copy /office-hours", payload="/office-hours"),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        status = execute_action(conn, row, fix, confirm=_always_no)
    assert status == "done"
