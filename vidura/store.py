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


EVIDENCE_POOL_CAP = 5


def record_suggestion(conn: sqlite3.Connection, s) -> None:
    """Ledger write with the design doc's core semantics:
    - a fix_id with an accepted/dismissed entry is NEVER re-recorded
    - a pending entry for the same fix_id MERGES (max confidence,
      pooled evidence capped at EVIDENCE_POOL_CAP, occurrences+1)
    - novel suggestions always insert fresh rows and never block each
      other (one dismissed novel must not silence all future novels)
    """
    now = _now()
    if not s.novel:
        blocked = conn.execute(
            "SELECT 1 FROM suggestions WHERE fix_id = ? AND status IN ('accepted', 'dismissed')",
            (s.fix_id,),
        ).fetchone()
        if blocked:
            return
        pending = conn.execute(
            "SELECT id, confidence, evidence, occurrences FROM suggestions "
            "WHERE fix_id = ? AND status = 'pending'",
            (s.fix_id,),
        ).fetchone()
        if pending:
            evidence = json.loads(pending["evidence"])
            for quote in s.evidence:
                if quote not in evidence and len(evidence) < EVIDENCE_POOL_CAP:
                    evidence.append(quote)
            conn.execute(
                "UPDATE suggestions SET confidence = ?, evidence = ?, "
                "occurrences = ?, blunt_summary = ?, updated_at = ? WHERE id = ?",
                (
                    max(pending["confidence"], s.confidence),
                    json.dumps(evidence),
                    pending["occurrences"] + 1,
                    s.blunt_summary,
                    now,
                    pending["id"],
                ),
            )
            conn.commit()
            return
    conn.execute(
        "INSERT INTO suggestions(fix_id, confidence, blunt_summary, evidence, "
        "novel, status, occurrences, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?)",
        (
            s.fix_id,
            s.confidence,
            s.blunt_summary,
            json.dumps(s.evidence[:EVIDENCE_POOL_CAP]),
            1 if s.novel else 0,
            now,
            now,
        ),
    )
    conn.commit()


def blocked_fix_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT fix_id FROM suggestions "
        "WHERE status IN ('accepted', 'dismissed') AND novel = 0"
    ).fetchall()
    return {r["fix_id"] for r in rows}


def ledger_entries(conn: sqlite3.Connection, status: str | None = None) -> list:
    if status is None:
        return conn.execute(
            "SELECT * FROM suggestions ORDER BY confidence DESC, id"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM suggestions WHERE status = ? ORDER BY confidence DESC, id",
        (status,),
    ).fetchall()


def set_status(conn: sqlite3.Connection, suggestion_id: int, status: str) -> bool:
    cur = conn.execute(
        "UPDATE suggestions SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), suggestion_id),
    )
    conn.commit()
    return cur.rowcount > 0


def ledger_summary_for_prompt(conn: sqlite3.Connection) -> list[dict]:
    """Compact ledger view for the reflector prompt: fix_id + status +
    summary only — evidence stays out to keep the payload lean."""
    rows = conn.execute(
        "SELECT fix_id, status, blunt_summary FROM suggestions ORDER BY id"
    ).fetchall()
    return [
        {"fix_id": r["fix_id"], "status": r["status"], "blunt_summary": r["blunt_summary"]}
        for r in rows
    ]
