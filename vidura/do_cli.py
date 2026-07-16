"""vidura-do: act on an accepted suggestion.

Design doc Decision 4/5: accepting is the decision (vidura-ledger
accept), doing is the follow-up (vidura-do). This CLI is a thin TTY
wrapper around vidura.executor.execute_action — it owns the
confirmation prompt (a real input() here) and translates executor
outcomes into process exit codes.
"""

import argparse
import subprocess
import sys

from vidura.executor import CwdGuardError, ExecutionDeclined, ExecutionError, execute_action
from vidura.fix_index import load_fix_index
from vidura.store import ledger_entries, open_db
from vidura.version import package_version


def _tty_confirm(prompt: str) -> bool:
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


def _find_fix(fix_id: str):
    for fix in load_fix_index():
        if fix.id == fix_id:
            return fix
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vidura-do",
        description="Act on an accepted suggestion: run its fix action after a confirmation prompt.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    parser.add_argument("id", type=int, help="ledger id of an accepted suggestion (see vidura-ledger list)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the exact action; execute nothing, record nothing",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip the TTY confirmation prompt. FOR UI CALLERS ONLY (e.g. the "
            "menu-bar pet) that have already shown the exact action and "
            "obtained explicit user confirmation themselves. --dry-run still "
            "wins over --yes. Every other gate (accept status, kill switch, "
            "audit, tiers) is unchanged."
        ),
    )
    args = parser.parse_args(argv)

    conn = open_db()
    try:
        rows = [r for r in ledger_entries(conn) if r["id"] == args.id]
        if not rows:
            print(f"vidura-do: no suggestion with id {args.id}", file=sys.stderr)
            return 1
        row = rows[0]

        if row["status"] != "accepted":
            print(
                f"vidura-do: suggestion {args.id} is {row['status']}, not accepted — "
                f"accept it first: vidura-ledger accept {args.id}",
                file=sys.stderr,
            )
            return 1

        fix = _find_fix(row["fix_id"])
        if fix is None or fix.action is None:
            remedy = fix.remedy if fix is not None else "(no remedy on record)"
            print(
                f"vidura-do: no executable action for this fix — remedy:\n{remedy}",
                file=sys.stderr,
            )
            return 1

        confirm = (lambda _: True) if args.yes else _tty_confirm
        try:
            status = execute_action(conn, row, fix, confirm=confirm, dry_run=args.dry_run)
        except ExecutionDeclined as e:
            print(str(e), file=sys.stderr)
            return 2
        except (PermissionError, CwdGuardError) as e:
            print(str(e), file=sys.stderr)
            return 1
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        except (ExecutionError, subprocess.TimeoutExpired) as e:
            # A confirmed action that failed to even run/complete
            # (timeout, missing binary, filesystem error) — already
            # audited by executor.py before this was raised. Never a
            # raw traceback: same exit code as an ordinary nonzero-exit
            # 'failed' status below.
            print(str(e), file=sys.stderr)
            return 3

        if status == "dry-run":
            print("dry-run: no side effects, nothing recorded.")
            return 0

        from vidura.store import executions_for

        last_audit = executions_for(conn, row["id"])[-1]
        audit_id = last_audit["id"]
        print(f"vidura-do: {status} (audit id {audit_id})")
        if status == "done" and "verify-failed" in (last_audit["detail"] or ""):
            print(
                "vidura-do: installed but verification failed — check manually",
                file=sys.stderr,
            )
        return 0 if status == "done" else 3
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
