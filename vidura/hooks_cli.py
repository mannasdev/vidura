"""vidura-hook: Claude Code lifecycle hooks integration.

Claude Code supports SessionEnd/SessionStart hooks configured in
~/.claude/settings.json (see `vidura-hook install`). Two subcommands
back those hooks:

- `session-end`: fires the moment a Claude Code session ends. Spawns a
  DETACHED incremental sweep (`vidura-sweep --batches 3`) so reflection
  happens close to the friction, not on the next 30-minute cron tick.
  Must return in milliseconds and never block Claude Code's shutdown —
  guarded by a recursion check (never sweep a reflector's own `claude -p`
  session), a cooldown, and a lockfile so concurrent/rapid session ends
  don't pile up sweeps.
- `session-start`: fires at the start of a new session. SessionStart
  stdout is appended to the session's context (per Claude Code docs), so
  this prints AT MOST one short line — only when suggestions are
  pending — and prints nothing otherwise. Any failure degrades to
  silence: a broken hook must never break a Claude Code session.

Both subcommands treat every exception as "exit 0, say nothing" —
matching the project's silence-is-correct principle (see reflect.py,
report.py) extended to the hook boundary itself.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from vidura.reflect import CLAUDE_CLI_CWD_TOKEN
from vidura.store import ledger_entries, open_db
from vidura.version import package_version

# Overridable via env/monkeypatch so tests never touch the real support
# dir or the real ~/.claude — see tests/test_hooks_cli.py.
SUPPORT_DIR_DEFAULT = Path.home() / "Library" / "Application Support" / "Vidura"
CLAUDE_SETTINGS_PATH_DEFAULT = Path.home() / ".claude" / "settings.json"

COOLDOWN_SECONDS = 900  # 15 minutes
LOCK_STALE_SECONDS = 45 * 60  # 45 minutes

# The raw substring form of the token, for matching against paths that
# might not carry the leading dash (e.g. a transcript path segment).
RECURSION_TOKEN_RAW = ".vidura/reflector-cwd"


def _support_dir() -> Path:
    override = os.environ.get("VIDURA_SUPPORT_DIR")
    return Path(override) if override else SUPPORT_DIR_DEFAULT


def _settings_path() -> Path:
    override = os.environ.get("VIDURA_CLAUDE_SETTINGS_PATH")
    return Path(override) if override else CLAUDE_SETTINGS_PATH_DEFAULT


def _cooldown_path() -> Path:
    return _support_dir() / "last-hook-sweep"


def _lock_path() -> Path:
    return _support_dir() / "sweep.lock"


def _log_path() -> Path:
    return _support_dir() / "hook-sweep.log"


# Hard cap on how much stdin we'll ever read for a hook payload. Claude
# Code hook payloads are small JSON objects; this bounds worst-case
# memory/parse cost if something feeds the hook a huge or unbounded
# stream instead of the expected payload.
STDIN_READ_CAP = 2_000_000


def _read_stdin_json() -> dict:
    """Best-effort stdin JSON parse. Missing/invalid/empty stdin must
    never crash the hook — treat any of it as an empty dict."""
    try:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read(STDIN_READ_CAP)
        if not raw or not raw.strip():
            return {}
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _walk_strings(obj):
    """Recursively yield every string value nested anywhere inside obj.

    Hook payloads are arbitrary, Claude-Code-controlled JSON — the
    recursion-guard token can show up several levels deep (e.g. inside a
    nested "session" dict or a list of paths), so the guard must walk
    the full structure rather than only the top-level values."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _walk_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_strings(item)


def _is_reflector_session(payload: dict) -> bool:
    """Recursion guard: a claude -p reflector session's own cwd (or
    transcript path) must never trigger another sweep. Matches on either
    the CLAUDE_CLI_CWD_TOKEN ("-vidura-reflector-cwd", the actual
    directory-name marker reflect.py creates) or the raw
    ".vidura/reflector-cwd" substring, checked against every string
    value found anywhere in the hook payload (cwd, transcript_path,
    nested dicts/lists, etc.) since the exact shape Claude Code uses
    isn't part of our contract."""
    for value in _walk_strings(payload):
        if CLAUDE_CLI_CWD_TOKEN in value or RECURSION_TOKEN_RAW in value:
            return True
    return False


def _within_cooldown() -> bool:
    path = _cooldown_path()
    try:
        value = float(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return False
    return (time.time() - value) < COOLDOWN_SECONDS


def _write_cooldown() -> None:
    path = _cooldown_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def _lock_blocks() -> bool:
    path = _lock_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False
    return (time.time() - mtime) < LOCK_STALE_SECONDS


def _resolve_sweep_binary() -> str:
    """Sibling of the running vidura-hook binary, falling back to PATH."""
    sibling = Path(sys.argv[0]).parent / "vidura-sweep"
    if sibling.exists():
        return str(sibling)
    found = shutil.which("vidura-sweep")
    return found or "vidura-sweep"


def cmd_session_end(argv: list[str]) -> int:
    payload = _read_stdin_json()
    if _is_reflector_session(payload):
        return 0
    # TOCTOU note: the cooldown and lock checks below are best-effort
    # gates, not mutexes — there's a window between checking and writing
    # each file where a second, near-simultaneous session-end could slip
    # through. That's tolerated on purpose: sweeps are resume-safe (a
    # sweep picks up wherever the last one left off) and a double-spawn
    # racing on the same SQLite ledger just degrades to one of them
    # skipping a batch, not to corruption or lost data.
    if _within_cooldown():
        return 0
    if _lock_blocks():
        return 0

    support_dir = _support_dir()
    support_dir.mkdir(parents=True, exist_ok=True)
    lock = _lock_path()
    log = _log_path()

    _write_cooldown()
    lock.write_text(str(time.time()), encoding="utf-8")

    sweep_bin = _resolve_sweep_binary()
    # NOTE: deliberately NOT `exec`— exec replaces the bash process image,
    # so a trap registered on it would never fire once the sweep binary
    # takes over (verified: bash -c 'trap ... EXIT; exec cmd' leaks the
    # trap). Running the sweep as a plain foreground command keeps bash
    # alive to run the trap on the way out, which is what actually
    # removes the lock.
    script = (
        f"trap {shlex.quote('rm -f ' + str(lock))} EXIT; "
        f"{shlex.quote(sweep_bin)} --batches 3"
    )
    try:
        with open(log, "a", encoding="utf-8") as log_f:
            subprocess.Popen(
                ["/bin/bash", "-c", script],
                stdout=log_f,
                stderr=log_f,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception:
        # Spawn failed — don't leave a lock nobody will ever clear.
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
    return 0


def cmd_session_start(argv: list[str]) -> int:
    try:
        payload = _read_stdin_json()
        if _is_reflector_session(payload):
            return 0
        conn = open_db()
        try:
            pending = ledger_entries(conn, status="pending")
        finally:
            conn.close()
        if pending:
            print(
                f"Vidura: {len(pending)} suggestion(s) pending — "
                "run vidura-ledger to review, vidura-do <id> to act."
            )
        return 0
    except Exception:
        return 0


def _load_settings(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _hook_command_string(event: str, hook_bin: str) -> str:
    subcommand = "session-end" if event == "SessionEnd" else "session-start"
    return f"{hook_bin} {subcommand}"


def _has_vidura_entry(entries: list, event: str) -> bool:
    for entry in entries:
        for hook in entry.get("hooks", []):
            if "vidura-hook" in hook.get("command", ""):
                return True
    return False


def cmd_install(argv: list[str]) -> int:
    settings_path = _settings_path()
    hook_bin = str(Path(sys.argv[0]).resolve().parent / "vidura-hook")

    original_text = None
    if settings_path.exists():
        original_text = settings_path.read_text(encoding="utf-8")
        try:
            json.loads(original_text)
        except json.JSONDecodeError:
            print(
                f"vidura-hook: existing settings.json is not valid JSON — "
                f"fix it first; nothing was changed ({settings_path})"
            )
            return 1

    settings = _load_settings(settings_path)
    changed = False
    hooks = settings.setdefault("hooks", {})

    for event in ("SessionEnd", "SessionStart"):
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            continue
        if _has_vidura_entry(entries, event):
            continue
        entries.append(
            {
                "hooks": [
                    {"type": "command", "command": _hook_command_string(event, hook_bin)}
                ]
            }
        )
        changed = True

    if not changed:
        print("vidura-hook: already installed for SessionEnd and SessionStart.")
        return 0

    if original_text is not None:
        backup_path = settings_path.parent / f"settings.json.vidura-backup-{int(time.time())}"
        backup_path.write_text(original_text, encoding="utf-8")

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"vidura-hook: installed hooks into {settings_path}")
    return 0


def cmd_uninstall(argv: list[str]) -> int:
    settings_path = _settings_path()
    if not settings_path.exists():
        print("vidura-hook: no settings.json found, nothing to do.")
        return 0

    settings = _load_settings(settings_path)
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        print("vidura-hook: not installed.")
        return 0

    changed = False
    for event in ("SessionEnd", "SessionStart"):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [
            entry
            for entry in entries
            if not _has_vidura_entry([entry], event)
        ]
        if len(kept) != len(entries):
            changed = True
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)

    if not changed:
        print("vidura-hook: not installed.")
        return 0

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"vidura-hook: removed hooks from {settings_path}")
    return 0


def cmd_status(argv: list[str]) -> int:
    settings_path = _settings_path()
    settings = _load_settings(settings_path)
    hooks = settings.get("hooks", {})
    for event in ("SessionEnd", "SessionStart"):
        entries = hooks.get(event, []) if isinstance(hooks, dict) else []
        installed = isinstance(entries, list) and _has_vidura_entry(entries, event)
        status = "installed" if installed else "not installed"
        print(f"{event}: {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vidura-hook",
        description="Claude Code lifecycle hooks: the hook entrypoints plus install/uninstall/status for ~/.claude/settings.json.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, blurb in (
        ("session-end", "SessionEnd hook: spawn a detached incremental sweep"),
        ("session-start", "SessionStart hook: print one line if suggestions are pending"),
        ("install", "add the hooks to ~/.claude/settings.json (backs up the original)"),
        ("uninstall", "remove the hooks from ~/.claude/settings.json"),
        ("status", "show whether the hooks are installed"),
    ):
        sub.add_parser(name, help=blurb, description=blurb)
    args, _rest = parser.parse_known_args(argv)

    if args.command == "session-end":
        return cmd_session_end(argv or [])
    if args.command == "session-start":
        return cmd_session_start(argv or [])
    if args.command == "install":
        return cmd_install(argv or [])
    if args.command == "uninstall":
        return cmd_uninstall(argv or [])
    if args.command == "status":
        return cmd_status(argv or [])
    return 1


if __name__ == "__main__":
    sys.exit(main())
