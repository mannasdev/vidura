"""vidura-do: act on an accepted suggestion.

Design doc Decision 4/5: accepting is the decision (vidura-ledger
accept), doing is the follow-up (vidura-do). This CLI is a thin TTY
wrapper around vidura.executor.execute_action — it owns the
confirmation prompt (a real input() here) and translates executor
outcomes into process exit codes.
"""

import argparse
import sys

from vidura.executor import ExecutionDeclined, execute_action
from vidura.fix_index import load_fix_index
from vidura.store import ledger_entries, open_db


def _tty_confirm(prompt: str) -> bool:
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


def _find_fix(fix_id: str):
    for fix in load_fix_index():
        if fix.id == fix_id:
            return fix
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidura-do")
    parser.add_argument("id", type=int)
    parser.add_argument("--dry-run", action="store_true")
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

        try:
            status = execute_action(conn, row, fix, confirm=_tty_confirm, dry_run=args.dry_run)
        except ExecutionDeclined as e:
            print(str(e), file=sys.stderr)
            return 2
        except PermissionError as e:
            print(str(e), file=sys.stderr)
            return 1

        if status == "dry-run":
            print("dry-run: no side effects, nothing recorded.")
            return 0

        from vidura.store import executions_for

        audit_id = executions_for(conn, row["id"])[-1]["id"]
        print(f"vidura-do: {status} (audit id {audit_id})")
        return 0 if status == "done" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
