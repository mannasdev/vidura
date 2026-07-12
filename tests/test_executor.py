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


def _nested_write_fix():
    # Scaffold targets like .claude/agents/<name>.md live under
    # directories most repos don't have yet — the WRITE tier must create
    # the missing parents itself (open("a") only creates the file).
    return Fix(
        id="code-review-by-author",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(
            tier=2,
            label="Write a code-reviewer subagent starter",
            payload="---\nname: code-reviewer\n---\n",
            target_file=".claude/agents/code-reviewer.md",
        ),
    )


def test_write_creates_missing_parent_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "code-review-by-author")
    status = execute_action(conn, row, _nested_write_fix(), confirm=_always_yes)
    assert status == "done"
    target = tmp_path / ".claude" / "agents" / "code-reviewer.md"
    assert target.read_text() == "---\nname: code-reviewer\n---\n"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"


def test_write_decline_creates_no_parent_directories(tmp_path, monkeypatch):
    """A declined WRITE must leave zero filesystem traces — parent dirs
    are created only after the user confirms, so declining a nested
    target can't leave an empty .claude/ tree behind."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "code-review-by-author")
    with pytest.raises(ExecutionDeclined):
        execute_action(conn, row, _nested_write_fix(), confirm=_always_no)
    assert not (tmp_path / ".claude").exists()
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "declined"


def test_write_dry_run_creates_no_parent_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "code-review-by-author")
    status = execute_action(conn, row, _nested_write_fix(), confirm=_always_yes, dry_run=True)
    assert status == "dry-run"
    assert not (tmp_path / ".claude").exists()
    assert executions_for(conn, row["id"]) == []


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


def test_run_requires_repo_false_executes_from_non_git_cwd(tmp_path, monkeypatch):
    """A machine-global install (requires_repo=False, e.g. skillfish)
    must not be blocked by the cwd guard — it writes to ~/.claude/skills
    regardless of cwd, so refusing outside a repo protects nothing."""
    monkeypatch.chdir(tmp_path)  # deliberately no .git anywhere
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "shotgun-debugging")
    fix = Fix(
        id="shotgun-debugging",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(
            tier=3,
            label="Install skill",
            payload="",
            argv=["npx", "-y", "skillfish@1.0.38", "add", "obra/superpowers", "systematic-debugging"],
            requires_repo=False,
        ),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "installed\n"
        mock_run.return_value.stderr = ""
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    mock_run.assert_called_once()


def test_run_requires_repo_true_still_refuses_outside_git_repo(tmp_path, monkeypatch):
    """The default (requires_repo=True) preserves the existing guard for
    project-scoped installs like `claude mcp add` (without -s)."""
    monkeypatch.chdir(tmp_path)  # no .git anywhere
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "manual-ui-verification")
    fix = Fix(
        id="manual-ui-verification",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(
            tier=3,
            label="Install the Playwright MCP",
            payload="",
            argv=["claude", "mcp", "add", "playwright", "--", "npx", "-y", "@playwright/mcp@0.0.78"],
        ),
    )
    with patch("vidura.executor.subprocess.run") as mock_run:
        with pytest.raises(CwdGuardError):
            execute_action(conn, row, fix, confirm=_always_yes)
        mock_run.assert_not_called()
    assert executions_for(conn, row["id"]) == []


def test_write_always_refuses_outside_git_repo_regardless_of_requires_repo(tmp_path, monkeypatch):
    """WRITE has no requires_repo escape hatch — even if a caller sets
    requires_repo=False on a tier-2 action, WRITE still refuses outside
    a repo because it resolves target_file against cwd."""
    monkeypatch.chdir(tmp_path)  # no .git anywhere
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
            label="Write CLAUDE.md",
            payload="# Project\n",
            target_file="CLAUDE.md",
            requires_repo=False,
        ),
    )
    with pytest.raises(CwdGuardError):
        execute_action(conn, row, fix, confirm=_always_yes)
    assert not (tmp_path / "CLAUDE.md").exists()
    assert executions_for(conn, row["id"]) == []


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


# ---------------------------------------------------------------------------
# post-install verification (verify_argv / verify_expect)
# ---------------------------------------------------------------------------


def _verify_fix(verify_argv=None, verify_expect=None):
    return Fix(
        id="manual-ui-verification",
        title="t",
        friction_patterns=["p"],
        remedy="r",
        confidence_floor=0.5,
        action=FixAction(
            tier=3,
            label="Install the Playwright MCP",
            payload="",
            argv=["claude", "mcp", "add", "playwright", "--", "npx", "-y", "@playwright/mcp@0.0.78"],
            verify_argv=verify_argv,
            verify_expect=verify_expect,
        ),
    )


def test_verify_success_path_records_verified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "manual-ui-verification")
    fix = _verify_fix(verify_argv=["claude", "mcp", "list"], verify_expect="playwright")

    install_result = type("R", (), {"returncode": 0, "stdout": "installed\n", "stderr": ""})()
    verify_result = type("R", (), {"returncode": 0, "stdout": "playwright: connected\n", "stderr": ""})()

    with patch("vidura.executor.subprocess.run", side_effect=[install_result, verify_result]) as mock_run:
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    assert mock_run.call_count == 2
    verify_call_args = mock_run.call_args_list[1]
    assert verify_call_args.args[0] == ["claude", "mcp", "list"]
    assert verify_call_args.kwargs["timeout"] == 30
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert "verified" in rows[0]["detail"]
    assert "verify-failed" not in rows[0]["detail"]


def test_verify_failed_path_status_still_done_message_shown(tmp_path, monkeypatch):
    """A verify that runs but doesn't show the expected substring never
    raises and never flips the RUN's own status — 'done' stays 'done',
    only the audit detail records the verify outcome."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "manual-ui-verification")
    fix = _verify_fix(verify_argv=["claude", "mcp", "list"], verify_expect="playwright")

    install_result = type("R", (), {"returncode": 0, "stdout": "installed\n", "stderr": ""})()
    verify_result = type("R", (), {"returncode": 0, "stdout": "no mcp servers configured\n", "stderr": ""})()

    with patch("vidura.executor.subprocess.run", side_effect=[install_result, verify_result]):
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert "verify-failed" in rows[0]["detail"]


def test_verify_subprocess_raising_is_audited_not_crashing(tmp_path, monkeypatch):
    """A verify command that itself raises (missing binary, timeout)
    must not propagate — it degrades to an audited verify-failed note,
    same as a verify that ran but showed the wrong output."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "manual-ui-verification")
    fix = _verify_fix(verify_argv=["claude", "mcp", "list"], verify_expect="playwright")

    install_result = type("R", (), {"returncode": 0, "stdout": "installed\n", "stderr": ""})()

    with patch(
        "vidura.executor.subprocess.run",
        side_effect=[install_result, FileNotFoundError("no such file: claude")],
    ):
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "done"
    rows = executions_for(conn, row["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert "verify-failed" in rows[0]["detail"]


def test_dry_run_never_runs_verify(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "manual-ui-verification")
    fix = _verify_fix(verify_argv=["claude", "mcp", "list"], verify_expect="playwright")
    with patch("vidura.executor.subprocess.run") as mock_run:
        status = execute_action(conn, row, fix, confirm=_always_yes, dry_run=True)
        mock_run.assert_not_called()
    assert status == "dry-run"
    assert executions_for(conn, row["id"]) == []


def test_verify_not_run_when_install_fails(tmp_path, monkeypatch):
    """Verify only runs after a successful (returncode 0) RUN — a
    failed install already tells its own story."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    conn = open_db(tmp_path / "db.sqlite")
    row = _suggestion_row(conn, "manual-ui-verification")
    fix = _verify_fix(verify_argv=["claude", "mcp", "list"], verify_expect="playwright")

    install_result = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom\n"})()

    with patch("vidura.executor.subprocess.run", side_effect=[install_result]) as mock_run:
        status = execute_action(conn, row, fix, confirm=_always_yes)
    assert status == "failed"
    assert mock_run.call_count == 1  # verify never ran
    rows = executions_for(conn, row["id"])
    assert rows[0]["status"] == "failed"


def test_verify_none_skips_verification_entirely(tmp_path, monkeypatch):
    """A RUN action with verify_argv=None (e.g. the skillfish skill
    installs) never attempts verification — audit detail is unchanged
    from pre-verify behavior."""
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
    assert mock_run.call_count == 1
    rows = executions_for(conn, row["id"])
    assert "verified" not in rows[0]["detail"]
    assert "verify-failed" not in rows[0]["detail"]
