"""Tier-dispatched action execution — design doc Decisions 1 and 3.

`execute_action` is the one entrypoint both `vidura-do` and (eventually)
the M3 pet call. It never decides on its own: every tier >=2 action goes
through an injected `confirm(prompt) -> bool` callable so tests (and the
pet's own UI) never touch a real TTY.

Hard rules enforced here (docs/design/m3-execution.md, Decision 3):
1. Never auto — tier >=2 always confirms with the exact content/argv shown.
2. Actions only ever come from fix-index entries (trusted, in code).
3. Everything is audited, including declines.
4. VIDURA_EXECUTION=off disables tiers >=2; COPY (tier 1) always allowed.
5. Callers are responsible for only invoking this on accepted suggestions
   (vidura-do enforces that at the CLI boundary).
"""

import os
import subprocess
from pathlib import Path
from typing import Callable

from vidura.fix_index import Fix
from vidura.store import record_execution

OUTPUT_HEAD_CHARS = 2000
RUN_TIMEOUT_SECONDS = 300
VERIFY_TIMEOUT_SECONDS = 30


class ExecutionDeclined(Exception):
    """Raised when the user declines a tier >=2 confirmation prompt."""


class ExecutionError(Exception):
    """Raised when a confirmed tier >=2 action fails to even run/complete
    (subprocess timeout, missing binary, or a filesystem error on the
    WRITE tier's open/write) — as opposed to running and exiting
    nonzero, which is the ordinary 'failed' status. Always raised AFTER
    record_execution has logged the attempt (status 'timeout' or
    'error'), so "everything is audited" holds even on this path."""


class CwdGuardError(Exception):
    """Raised when WRITE/RUN refuses to run because Path.cwd() looks
    unsafe (filesystem root, $HOME, or not inside a git repo) — see
    _guard_cwd. No audit record: the action never reached the point of
    asking, same as the kill-switch PermissionError."""


def execution_enabled() -> bool:
    """Kill switch: VIDURA_EXECUTION=off disables tiers >=2 (Decision 3.4)."""
    return os.environ.get("VIDURA_EXECUTION") != "off"


def _guard_cwd() -> None:
    """WRITE (tier 2) and RUN (tier 3) both act on/from Path.cwd() — a
    write appends to a file resolved against it, a run executes from it.
    When the pet is launched from Finder (or any non-terminal launcher),
    its process cwd is "/" — the WRITE tier would then resolve
    "CLAUDE.md" to /CLAUDE.md, a real, damaging path (outside-voice
    finding #5). Refuse when cwd is exactly the filesystem root or the
    user's home directory, or when it's not inside a git repo at all
    (cheap check: a .git in cwd or any of its parents) — COPY (tier 1)
    is unaffected, it never touches the filesystem.

    Callers gate this: WRITE always calls it (it resolves target_file
    against cwd, so a repo-less invocation is never safe). RUN only
    calls it when action.requires_repo is True — a machine-global
    install (e.g. skillfish, writing to ~/.claude/skills regardless of
    cwd) has no reason to refuse just because cwd isn't a repo."""
    cwd = Path.cwd().resolve()
    if cwd == Path(cwd.anchor) or cwd == Path.home().resolve():
        raise CwdGuardError(
            "vidura: refusing to run from "
            f"{cwd} — run vidura-do from a terminal inside the target repo"
        )
    if not any((candidate / ".git").exists() for candidate in (cwd, *cwd.parents)):
        raise CwdGuardError(
            f"vidura: {cwd} is not inside a git repo — "
            "run vidura-do from a terminal inside the target repo"
        )


def execute_action(
    conn,
    suggestion_row,
    fix: Fix,
    *,
    confirm: Callable[[str], bool],
    dry_run: bool = False,
) -> str:
    """Dispatch fix.action by tier. Returns a status string:
    'done' | 'failed' | 'declined' | 'dry-run'.

    Raises ExecutionDeclined when the user declines a confirmation prompt
    (after recording the decline in the audit log). Raises PermissionError
    when the kill switch blocks a tier >=2 action (no audit record — the
    action never even reached the point of asking). Raises CwdGuardError
    when WRITE/RUN's cwd looks unsafe (also no audit record, same
    reasoning). Raises ExecutionError when a confirmed WRITE/RUN action
    fails to even run/complete (timeout, missing binary, filesystem
    error) — audited first, then re-raised.
    """
    action = fix.action
    if action is None:
        raise ValueError("vidura: fix has no executable action")
    suggestion_id = suggestion_row["id"]

    if action.tier >= 2 and not dry_run and not execution_enabled():
        raise PermissionError(
            "vidura: execution disabled (VIDURA_EXECUTION=off) — "
            "tiers 2+ (WRITE/RUN) are blocked; unset VIDURA_EXECUTION to re-enable"
        )
    # WRITE (tier 2) is always guarded — it resolves target_file against
    # cwd, so a repo-less invocation is never safe regardless of the
    # action's requires_repo flag. RUN (tier 3) only guards when the
    # action itself is repo-scoped (requires_repo=True, the default) —
    # a machine-global install has nothing to protect by refusing.
    if not dry_run:
        if action.tier == 2 or (action.tier == 3 and action.requires_repo):
            _guard_cwd()

    if action.tier == 1:
        return _execute_copy(conn, suggestion_id, fix, dry_run=dry_run)
    if action.tier == 2:
        return _execute_write(conn, suggestion_id, fix, confirm=confirm, dry_run=dry_run)
    if action.tier == 3:
        return _execute_run(conn, suggestion_id, fix, confirm=confirm, dry_run=dry_run)
    raise ValueError(f"vidura: unsupported action tier {action.tier}")


def _execute_copy(conn, suggestion_id: int, fix: Fix, *, dry_run: bool) -> str:
    action = fix.action
    if dry_run:
        print(f"[dry-run] would copy to clipboard:\n{action.payload}")
        return "dry-run"
    result = subprocess.run(["pbcopy"], input=action.payload.encode(), check=False)
    status = "done" if result.returncode == 0 else "failed"
    record_execution(
        conn,
        suggestion_id=suggestion_id,
        fix_id=fix.id,
        tier=action.tier,
        detail=f"copied to clipboard: {action.payload!r}",
        status=status,
        exit_code=result.returncode,
    )
    return status


def _execute_write(conn, suggestion_id: int, fix: Fix, *, confirm, dry_run: bool) -> str:
    action = fix.action
    cwd = Path.cwd().resolve()
    target = (cwd / action.target_file).resolve()
    if not target.is_relative_to(cwd):
        raise ValueError(
            f"vidura: refusing to write outside the working directory: {action.target_file!r}"
        )
    if dry_run:
        print(f"[dry-run] would append to {target}:\n{action.payload}")
        return "dry-run"

    prompt = (
        f"Append the following block to {target}?\n"
        f"{'-' * 40}\n{action.payload}\n{'-' * 40}\n[y/N] "
    )
    if not confirm(prompt):
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=f"declined: append to {target}",
            status="declined",
        )
        raise ExecutionDeclined(f"vidura: declined writing to {target}")

    try:
        # Scaffold targets (e.g. ".claude/agents/code-reviewer.md") often
        # live under directories the repo doesn't have yet — open("a")
        # creates a missing file but not missing parents. Created only
        # here, post-confirm: a declined or dry-run action must leave
        # zero filesystem traces. The containment guard above already
        # proved target resolves inside cwd, so target.parent does too —
        # this can never mkdir outside the repo.
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as f:
            f.write(action.payload)
    except OSError as exc:
        # Post-confirm: the user already said yes, so a filesystem error
        # here (permission denied, disk full, target vanished) must
        # still be audited — "everything is audited" (Decision 3) can't
        # have a hole where a confirmed action silently vanishes into an
        # uncaught traceback instead of a logged row.
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=f"error: append to {target}: {exc}",
            status="error",
        )
        raise ExecutionError(f"vidura: writing to {target} failed: {exc}") from exc
    record_execution(
        conn,
        suggestion_id=suggestion_id,
        fix_id=fix.id,
        tier=action.tier,
        detail=f"appended block to {target}",
        status="done",
    )
    return "done"


def _execute_run(conn, suggestion_id: int, fix: Fix, *, confirm, dry_run: bool) -> str:
    action = fix.action
    argv = action.argv
    if dry_run:
        print(f"[dry-run] would run: {' '.join(argv)}")
        return "dry-run"

    prompt = f"Run the following command?\n  {' '.join(argv)}\n[y/N] "
    if not confirm(prompt):
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=f"declined: {' '.join(argv)}",
            status="declined",
        )
        raise ExecutionDeclined(f"vidura: declined running {' '.join(argv)}")

    try:
        result = subprocess.run(
            argv, shell=False, timeout=RUN_TIMEOUT_SECONDS, capture_output=True
        )
    except subprocess.TimeoutExpired as exc:
        # Post-confirm: the user already said yes. A hung command that
        # never returns must still leave an audit row — the old code
        # let TimeoutExpired/FileNotFoundError/OSError escape uncaught
        # here, meaning a confirmed RUN action could vanish with NO
        # record_execution row at all (outside-voice finding #1).
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=f"timeout: {' '.join(argv)}",
            status="timeout",
        )
        raise ExecutionError(f"vidura: running {' '.join(argv)} timed out after {RUN_TIMEOUT_SECONDS}s") from exc
    except (FileNotFoundError, OSError) as exc:
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=f"error: {' '.join(argv)}: {exc}",
            status="error",
        )
        raise ExecutionError(f"vidura: running {' '.join(argv)} failed: {exc}") from exc
    status = "done" if result.returncode == 0 else "failed"
    output_head = None
    try:
        stdout = (
            result.stdout.decode(errors="replace")
            if isinstance(result.stdout, bytes)
            else (result.stdout or "")
        )
        stderr = (
            result.stderr.decode(errors="replace")
            if isinstance(result.stderr, bytes)
            else (result.stderr or "")
        )
        output_head = (stdout + stderr)[:OUTPUT_HEAD_CHARS]
        detail = f"ran: {' '.join(argv)}"
        # Post-install verification (design doc: "Do proves the action
        # worked") only runs after a successful RUN — a nonzero/failed
        # exit already tells its own story, verifying on top of a known
        # failure would just be noise. A verify failure degrades to
        # honesty, not to error: the install may still be fine (e.g. the
        # verify command's own output format shifted), so it must never
        # flip a 'done' RUN into 'failed' or raise — it only annotates
        # the SAME audit row's detail, which is the one place both do_cli
        # and a human reading the audit log look.
        if status == "done" and action.verify_argv:
            verify_note = _run_verify(action.verify_argv, action.verify_expect)
            detail = f"{detail} ({verify_note})"
    finally:
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=detail,
            status=status,
            exit_code=result.returncode,
            output_head=output_head,
        )
    return status


def _run_verify(verify_argv: list[str], verify_expect: str | None) -> str:
    """Run a post-install verification command and return a short note
    for the audit detail ("verified" / "verify-failed: <head>"). Never
    raises: a verify subprocess that times out, can't be found, or
    otherwise blows up is caught and reported the same way as a verify
    that ran but didn't show the expected substring — verification
    failing is informational, never fatal (the RUN itself already
    succeeded and is already recorded as 'done')."""
    try:
        result = subprocess.run(
            verify_argv, shell=False, timeout=VERIFY_TIMEOUT_SECONDS, capture_output=True
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return f"verify-failed: {exc}"[:OUTPUT_HEAD_CHARS]

    stdout = (
        result.stdout.decode(errors="replace")
        if isinstance(result.stdout, bytes)
        else (result.stdout or "")
    )
    stderr = (
        result.stderr.decode(errors="replace")
        if isinstance(result.stderr, bytes)
        else (result.stderr or "")
    )
    output = stdout + stderr

    if result.returncode != 0:
        return f"verify-failed: {output[:OUTPUT_HEAD_CHARS]}"
    if verify_expect is not None and verify_expect not in output:
        return f"verify-failed: {output[:OUTPUT_HEAD_CHARS]}"
    return "verified"
