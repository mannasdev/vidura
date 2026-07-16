"""vidura-ledger: list / accept / dismiss suggestions.

Accept/dismiss is the feedback loop the whole design leans on: a
dismissed fix_id is never suggested again (store.record_suggestion
blocks it), and statuses steer future reflector prompts via the
ledger summary.
"""

import argparse
import json
import sys

from vidura.fix_index import load_fix_index
from vidura.store import _sanitize, ledger_entries, mark_celebrated, open_db, set_status
from vidura.version import package_version


def _list(conn) -> None:
    rows = ledger_entries(conn)
    if not rows:
        print("Ledger is empty.")
        return
    for r in rows:
        novel = " (novel)" if r["novel"] else ""
        print(f"[{r['id']}] {r['status']:9s} {r['fix_id']}{novel} confidence={r['confidence']:.2f} seen_in={r['occurrences']}")
        print(f"      {_sanitize(r['blunt_summary'])}")


def _action_lookup() -> dict[str, str]:
    """fix_id -> action label, for fixes that carry an executable action."""
    return {fix.id: fix.action.label for fix in load_fix_index() if fix.action is not None}


def _list_json(conn) -> None:
    """Machine-readable ledger — design doc UI prelude: stdout carries
    ONLY the JSON array (no banners) so UI callers (the pet) can pipe
    it straight into a decoder. Enriched with has_action/action_label
    so the pet knows whether to render a Do button without its own
    fix-index lookup (Task 2's popover, plan Task 1 item 1)."""
    action_labels = _action_lookup()
    rows = ledger_entries(conn)
    out = []
    for r in rows:
        label = action_labels.get(r["fix_id"])
        out.append(
            {
                "id": r["id"],
                "fix_id": r["fix_id"],
                "status": r["status"],
                "confidence": r["confidence"],
                "occurrences": r["occurrences"],
                "blunt_summary": _sanitize(r["blunt_summary"]),
                "evidence": json.loads(r["evidence"]),
                "novel": bool(r["novel"]),
                "updated_at": r["updated_at"],
                "has_action": label is not None,
                "action_label": label,
            }
        )
    print(json.dumps(out))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vidura-ledger",
        description="List, accept, or dismiss suggestions (no subcommand: list).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    sub = parser.add_subparsers(dest="command")
    list_blurb = "show all suggestions (the default when no subcommand is given)"
    list_parser = sub.add_parser("list", help=list_blurb, description=list_blurb)
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the ledger as a JSON array (stdout carries only JSON, for UI callers)",
    )
    for action, blurb in (
        ("accept", "mark a suggestion accepted (act on it with vidura-do <id>)"),
        ("dismiss", "dismiss a suggestion; a dismissed fix is never re-suggested"),
        ("celebrate", "mark an adopted suggestion celebrated (the pet's proud state fires once)"),
    ):
        p = sub.add_parser(action, help=blurb, description=blurb)
        p.add_argument("id", type=int, help="suggestion id (first column of vidura-ledger list)")
    args = parser.parse_args(argv)

    conn = open_db()
    try:
        if args.command in (None, "list"):
            if getattr(args, "as_json", False):
                _list_json(conn)
            else:
                _list(conn)
            return 0
        if args.command == "celebrate":
            if not mark_celebrated(conn, args.id):
                print(f"vidura-ledger: no suggestion with id {args.id}", file=sys.stderr)
                return 1
            print(f"Suggestion {args.id} celebrated.")
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
