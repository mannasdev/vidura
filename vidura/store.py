"""M1-lite state: seen-session tracking + the suggestion ledger.

SQLite (stdlib), one file, default under ~/Library/Application Support/
Vidura/ per design doc §6 — one folder to delete = total erasure. The
ledger is load-bearing: it is what makes Vidura a counselor with a
memory instead of a Clippy (never re-suggest a dismissal), and it is
the audit log the eventual execution capability writes to.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_DEFAULT_PATH = Path.home() / "Library" / "Application Support" / "Vidura" / "vidura.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    reflected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fix_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    blunt_summary TEXT NOT NULL,
    evidence TEXT NOT NULL,
    novel INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    occurrences INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or Path(os.environ.get("VIDURA_DB_PATH", str(DB_DEFAULT_PATH)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def needs_reflection(conn: sqlite3.Connection, path: Path) -> bool:
    """True if this session file is unseen or has changed (mtime/size)
    since it was last reflected. Active session files keep growing —
    a changed file gets re-reflected in full; dedup of its repeated
    suggestions is the ledger's job, not this function's."""
    st = path.stat()
    row = conn.execute(
        "SELECT mtime, size FROM sessions WHERE path = ?", (str(path),)
    ).fetchone()
    if row is None:
        return True
    return not (abs(row["mtime"] - st.st_mtime) < 1e-6 and row["size"] == st.st_size)


def mark_reflected(conn: sqlite3.Connection, path: Path) -> None:
    st = path.stat()
    conn.execute(
        """INSERT INTO sessions(path, mtime, size, reflected_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
             mtime = excluded.mtime,
             size = excluded.size,
             reflected_at = excluded.reflected_at""",
        (str(path), st.st_mtime, st.st_size, _now()),
    )
    conn.commit()
