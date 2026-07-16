"""vidura-state: print the current mood + character as machine-readable
JSON.

This is the read-model the future menu-bar pet polls — stdout carries
ONLY the JSON payload (no banners, no progress text) so callers can
pipe it straight into a JSON parser.

character/character_since/character_reason are ALWAYS present (an
additive contract change over the mood-only payload): a fresh install
with no character_history row yet defaults to the "face" placeholder
so consumers never have to guess which keys exist.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from vidura.mood import compute_mood
from vidura.store import current_character, open_db
from vidura.version import package_version

DEFAULT_CHARACTER = "face"
DEFAULT_CHARACTER_REASON = "still getting to know you"


def main(argv: list[str] | None = None) -> int:
    # --help/--version must exit before the DB is even opened.
    parser = argparse.ArgumentParser(
        prog="vidura-state",
        description="Print the pet's current mood + character state as JSON.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    parser.parse_args(argv)

    conn = open_db()
    try:
        result = compute_mood(conn)
        row = current_character(conn)
    finally:
        conn.close()
    if row is None:
        result["character"] = DEFAULT_CHARACTER
        result["character_since"] = datetime.now(timezone.utc).isoformat()
        result["character_reason"] = DEFAULT_CHARACTER_REASON
    else:
        result["character"] = row["character"]
        result["character_since"] = row["assigned_at"]
        result["character_reason"] = row["reason"]
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
