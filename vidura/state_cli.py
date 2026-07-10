"""vidura-state: print the current mood as machine-readable JSON.

This is the read-model the future menu-bar pet polls — stdout carries
ONLY the JSON payload (no banners, no progress text) so callers can
pipe it straight into a JSON parser.
"""

import json
import sys

from vidura.mood import compute_mood
from vidura.store import open_db


def main(argv: list[str] | None = None) -> int:
    conn = open_db()
    try:
        result = compute_mood(conn)
    finally:
        conn.close()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
