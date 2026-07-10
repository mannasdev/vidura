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


class ExecutionDeclined(Exception):
    """Raised when the user declines a tier >=2 confirmation prompt."""


def execution_enabled() -> bool:
    """Kill switch: VIDURA_EXECUTION=off disables tiers >=2 (Decision 3.4)."""
    return os.environ.get("VIDURA_EXECUTION") != "off"


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
    action never even reached the point of asking).
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

    with target.open("a") as f:
        f.write(action.payload)
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

    result = subprocess.run(
        argv, shell=False, timeout=RUN_TIMEOUT_SECONDS, capture_output=True
    )
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
    finally:
        record_execution(
            conn,
            suggestion_id=suggestion_id,
            fix_id=fix.id,
            tier=action.tier,
            detail=f"ran: {' '.join(argv)}",
            status=status,
            exit_code=result.returncode,
            output_head=output_head,
        )
    return status
