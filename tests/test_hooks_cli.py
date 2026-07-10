import io
import json
import time

import pytest

from vidura import hooks_cli
from vidura.hooks_cli import (
    RECURSION_TOKEN_RAW,
    cmd_install,
    cmd_session_end,
    cmd_session_start,
    cmd_status,
    cmd_uninstall,
    main,
)
from vidura.reflect import CLAUDE_CLI_CWD_TOKEN
from vidura.store import open_db, record_suggestion
from tests.test_store import _sugg


def _setup(tmp_path, monkeypatch, db_name="db.sqlite"):
    support = tmp_path / "support"
    settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setenv("VIDURA_SUPPORT_DIR", str(support))
    monkeypatch.setenv("VIDURA_CLAUDE_SETTINGS_PATH", str(settings))
    monkeypatch.setenv("VIDURA_DB_PATH", str(tmp_path / db_name))
    return support, settings


def _stdin(monkeypatch, payload):
    text = json.dumps(payload) if payload is not None else ""
    stream = io.StringIO(text)
    stream.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", stream)


# ---------------------------------------------------------------------------
# recursion guard
# ---------------------------------------------------------------------------

def test_session_end_recursion_guard_token_form(tmp_path, monkeypatch):
    support, _ = _setup(tmp_path, monkeypatch)
    _stdin(monkeypatch, {"cwd": f"/Users/x/{CLAUDE_CLI_CWD_TOKEN}/whatever"})
    assert cmd_session_end([]) == 0
    assert not (support / "sweep.lock").exists()
    assert not (support / "last-hook-sweep").exists()


def test_session_end_recursion_guard_raw_form(tmp_path, monkeypatch):
    support, _ = _setup(tmp_path, monkeypatch)
    _stdin(monkeypatch, {"cwd": f"/Users/x/{RECURSION_TOKEN_RAW}"})
    assert cmd_session_end([]) == 0
    assert not (support / "sweep.lock").exists()


def test_session_start_recursion_guard_silent(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    conn = open_db()
    record_suggestion(conn, _sugg())
    conn.close()
    _stdin(monkeypatch, {"transcript_path": f"/x/{CLAUDE_CLI_CWD_TOKEN}/y.jsonl"})
    assert cmd_session_start([]) == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# cooldown / lock
# ---------------------------------------------------------------------------

def test_cooldown_blocks_within_window(tmp_path, monkeypatch):
    support, _ = _setup(tmp_path, monkeypatch)
    _stdin(monkeypatch, {})
    monkeypatch.setattr(hooks_cli, "_resolve_sweep_binary", lambda: "/bin/true")
    assert cmd_session_end([]) == 0
    lock = support / "sweep.lock"
    assert lock.exists()
    lock.unlink()  # simulate sweep having already finished & cleaned up
    _stdin(monkeypatch, {})
    assert cmd_session_end([]) == 0
    assert not lock.exists()  # blocked by cooldown, never re-spawned


def test_cooldown_allows_after_window(tmp_path, monkeypatch):
    support, _ = _setup(tmp_path, monkeypatch)
    support.mkdir(parents=True)
    (support / "last-hook-sweep").write_text(str(time.time() - 1000), encoding="utf-8")
    _stdin(monkeypatch, {})
    monkeypatch.setattr(hooks_cli, "_resolve_sweep_binary", lambda: "/bin/true")
    assert cmd_session_end([]) == 0
    assert (support / "sweep.lock").exists()


def test_stale_lock_ignored(tmp_path, monkeypatch):
    support, _ = _setup(tmp_path, monkeypatch)
    support.mkdir(parents=True)
    lock = support / "sweep.lock"
    lock.write_text("x", encoding="utf-8")
    old = time.time() - (46 * 60)
    import os

    os.utime(lock, (old, old))
    _stdin(monkeypatch, {})
    monkeypatch.setattr(hooks_cli, "_resolve_sweep_binary", lambda: "/bin/true")
    assert cmd_session_end([]) == 0
    # lock got rewritten (fresh mtime) by this run's spawn attempt
    assert lock.exists()
    assert (time.time() - lock.stat().st_mtime) < 5


def test_fresh_lock_blocks(tmp_path, monkeypatch):
    support, _ = _setup(tmp_path, monkeypatch)
    support.mkdir(parents=True)
    lock = support / "sweep.lock"
    lock.write_text("x", encoding="utf-8")
    _stdin(monkeypatch, {})
    assert cmd_session_end([]) == 0
    assert not (support / "last-hook-sweep").exists()  # never got past the lock guard


def test_malformed_stdin_does_not_crash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(hooks_cli, "_resolve_sweep_binary", lambda: "/bin/true")
    _stdin(monkeypatch, None)
    assert cmd_session_end([]) == 0
    _stdin(monkeypatch, None)
    assert cmd_session_start([]) == 0


def test_malformed_stdin_json_garbage(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    stream = io.StringIO("{not valid json")
    stream.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", stream)
    assert cmd_session_start([]) == 0


# ---------------------------------------------------------------------------
# session-start pending count
# ---------------------------------------------------------------------------

def test_session_start_prints_line_when_pending(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    conn = open_db()
    record_suggestion(conn, _sugg())
    conn.close()
    _stdin(monkeypatch, {})
    assert cmd_session_start([]) == 0
    out = capsys.readouterr().out
    assert out == "Vidura: 1 suggestion(s) pending — run vidura-ledger to review, vidura-do <id> to act.\n"


def test_session_start_silent_when_no_pending(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    conn = open_db()
    conn.close()
    _stdin(monkeypatch, {})
    assert cmd_session_start([]) == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# install / uninstall / status
# ---------------------------------------------------------------------------

def test_install_merges_with_existing_unrelated_hooks(tmp_path, monkeypatch):
    _, settings = _setup(tmp_path, monkeypatch)
    settings.parent.mkdir(parents=True)
    existing = {
        "hooks": {
            "SessionEnd": [{"hooks": [{"type": "command", "command": "/usr/bin/other-tool"}]}]
        },
        "someOtherKey": {"nested": True},
    }
    settings.write_text(json.dumps(existing), encoding="utf-8")

    assert cmd_install([]) == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["someOtherKey"] == {"nested": True}
    session_end_cmds = [h["command"] for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert "/usr/bin/other-tool" in session_end_cmds
    assert any("vidura-hook session-end" in c for c in session_end_cmds)
    session_start_cmds = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
    assert any("vidura-hook session-start" in c for c in session_start_cmds)

    backups = list(tmp_path.glob("claude/settings.json.vidura-backup-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == existing


def test_install_idempotent_no_duplicates(tmp_path, monkeypatch):
    _, settings = _setup(tmp_path, monkeypatch)
    assert cmd_install([]) == 0
    first = json.loads(settings.read_text(encoding="utf-8"))
    assert cmd_install([]) == 0
    second = json.loads(settings.read_text(encoding="utf-8"))
    assert first == second
    assert len(second["hooks"]["SessionEnd"]) == 1
    assert len(second["hooks"]["SessionStart"]) == 1
    # only one backup ever created (second install made no changes)
    backups = list(tmp_path.glob("claude/settings.json.vidura-backup-*"))
    assert len(backups) == 0  # no settings.json existed before first install


def test_install_creates_settings_when_missing(tmp_path, monkeypatch):
    _, settings = _setup(tmp_path, monkeypatch)
    assert not settings.exists()
    assert cmd_install([]) == 0
    assert settings.exists()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "SessionEnd" in data["hooks"]
    assert "SessionStart" in data["hooks"]


def test_uninstall_removes_only_vidura_entries(tmp_path, monkeypatch):
    _, settings = _setup(tmp_path, monkeypatch)
    settings.parent.mkdir(parents=True)
    existing = {
        "hooks": {
            "SessionEnd": [{"hooks": [{"type": "command", "command": "/usr/bin/other-tool"}]}]
        }
    }
    settings.write_text(json.dumps(existing), encoding="utf-8")
    assert cmd_install([]) == 0
    assert cmd_uninstall([]) == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    session_end_cmds = [h["command"] for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert session_end_cmds == ["/usr/bin/other-tool"]
    assert "SessionStart" not in data["hooks"]


def test_status_reports_installed_state(tmp_path, monkeypatch, capsys):
    _, settings = _setup(tmp_path, monkeypatch)
    cmd_status([])
    out = capsys.readouterr().out
    assert "SessionEnd: not installed" in out
    assert "SessionStart: not installed" in out

    cmd_install([])
    cmd_status([])
    out = capsys.readouterr().out
    assert "SessionEnd: installed" in out
    assert "SessionStart: installed" in out


def test_main_dispatches_subcommands(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)
    assert main(["status"]) == 0
