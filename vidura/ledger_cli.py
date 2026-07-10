"""vidura-ledger: list / accept / dismiss suggestions.

Accept/dismiss is the feedback loop the whole design leans on: a
dismissed fix_id is never suggested again (store.record_suggestion
blocks it), and statuses steer future reflector prompts via the
ledger summary.
"""

import argparse
import sys

from vidura.store import _sanitize, ledger_entries, open_db, set_status


def _list(conn) -> None:
    rows = ledger_entries(conn)
    if not rows:
        print("Ledger is empty.")
        return
    for r in rows:
        novel = " (novel)" if r["novel"] else ""
        print(f"[{r['id']}] {r['status']:9s} {r['fix_id']}{novel} confidence={r['confidence']:.2f} seen_in={r['occurrences']}")
        print(f"      {_sanitize(r['blunt_summary'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidura-ledger")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list")
    for action in ("accept", "dismiss"):
        p = sub.add_parser(action)
        p.add_argument("id", type=int)
    args = parser.parse_args(argv)

    conn = open_db()
    try:
        if args.command in (None, "list"):
            _list(conn)
            return 0
        if not set_status(conn, args.id, "accepted" if args.command == "accept" else "dismissed"):
            print(f"vidura-ledger: no suggestion with id {args.id}", file=sys.stderr)
            return 1
        print(f"Suggestion {args.id} {args.command}ed.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
