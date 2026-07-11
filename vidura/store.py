"""M1-lite state: seen-session tracking + the suggestion ledger.

SQLite (stdlib), one file, default under ~/Library/Application Support/
Vidura/ per design doc §6 — one folder to delete = total erasure. The
ledger is load-bearing: it is what makes Vidura a counselor with a
memory instead of a Clippy (never re-suggest a dismissal), and it is
the audit log the eventual execution capability writes to.
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_DEFAULT_PATH = Path.home() / "Library" / "Application Support" / "Vidura" / "vidura.db"

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _sanitize(text: str) -> str:
    """Strip ASCII control chars (keeping \\n and \\t) from
    model-echoed transcript text — evidence quotes and summaries can
    carry ANSI escape sequences from the original terminal session."""
    return _CONTROL_CHARS_RE.sub("", text)

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

SCHEMA_VERSION = 6

_SCHEMA_V2 = """
ALTER TABLE sessions ADD COLUMN streaks INTEGER;
ALTER TABLE sessions ADD COLUMN errors INTEGER;
ALTER TABLE sessions ADD COLUMN duration_seconds REAL;
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_path TEXT NOT NULL,
    text TEXT NOT NULL,
    user_turns INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suggestion_id INTEGER NOT NULL,
    fix_id TEXT NOT NULL,
    tier INTEGER NOT NULL,
    detail TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    exit_code INTEGER,
    output_head TEXT,
    status TEXT NOT NULL
);
"""

_SCHEMA_V4 = """
ALTER TABLE suggestions ADD COLUMN celebrated INTEGER NOT NULL DEFAULT 0;
"""

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS character_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character TEXT NOT NULL,
    reason TEXT NOT NULL,
    metrics TEXT NOT NULL,
    assigned_at TEXT NOT NULL
);
"""

_SCHEMA_V2_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

# v6: supermemory replaces the homegrown FTS5 chunk store as THE memory
# backend (docs/design/supermemory-adoption.md). Chunk memory is derived
# data (rebuilds from future sweeps), so this migration DROPs the chunks
# table, its FTS5 shadow index, and the sync triggers that kept them in
# lockstep — no backfill. State tables (sessions, suggestions,
# executions, character_history) are untouched.
_SCHEMA_V6 = """
DROP TRIGGER IF EXISTS chunks_ai;
DROP TRIGGER IF EXISTS chunks_ad;
DROP TABLE IF EXISTS chunks_fts;
DROP TABLE IF EXISTS chunks;
"""

# Indexes only — no schema/user_version bump needed (CREATE INDEX IF NOT
# EXISTS is idempotent on every open_db call, so a dedicated migration
# step would just be ceremony). sessions.mtime backs character.py's
# rolling-window scan and the pet's 30s poll of "what's new"; suggestions
# status backs ledger_entries/blocked_fix_ids' WHERE status = ... filters
# — both are polled every 60s by the pet (design review finding #8,
# performance).
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_sessions_mtime ON sessions(mtime);
CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or Path(os.environ.get("VIDURA_DB_PATH", str(DB_DEFAULT_PATH)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Explicit concurrency posture — this db is opened by up to 3
    # independent OS processes at once: the pet's own 30-min ambient
    # sweep (StateModel.swift), the SessionEnd hook's detached sweep
    # (hooks_cli.py), and an interactive CLI (vidura-ledger/vidura-do/a
    # manual vidura-sweep). WAL lets readers and the one writer proceed
    # without blocking each other; busy_timeout makes a writer-vs-writer
    # collision retry for 5s instead of raising "database is locked"
    # immediately (sweep.py's own process-level lock is the primary
    # writer-serialization mechanism — this is the belt-and-braces
    # fallback for the cases it doesn't cover, e.g. a CLI command racing
    # a sweep).
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    conn.executescript(_INDEXES)
    conn.commit()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 2:
        conn.executescript(_SCHEMA_V2)
        try:
            conn.executescript(_SCHEMA_V2_FTS)
        except sqlite3.OperationalError:
            # custom Python build without FTS5. This whole branch is
            # legacy-upgrade-path only now: v6 (below) unconditionally
            # DROPs chunks/chunks_fts on every db, since supermemory
            # replaced the homegrown FTS5 chunk store as THE memory
            # backend. A pre-v2 db still walks through v2 on its way to
            # v6, so this create (and its failure mode) has to stay
            # here to not break that upgrade path — but nothing reads
            # chunks_fts by the time open_db returns on any db, old or
            # new. Warn once, never crash (silence principle).
            print("vidura: sqlite lacks FTS5; skipping legacy chunks_fts create (dropped by v6 anyway)", file=sys.stderr)
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        version = 2
    if version < 3:
        conn.executescript(_SCHEMA_V3)
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
        version = 3
    if version < 4:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(suggestions)")}
        if "celebrated" not in cols:
            conn.executescript(_SCHEMA_V4)
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
        version = 4
    if version < 5:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "character_history" not in tables:
            conn.executescript(_SCHEMA_V5)
        conn.execute("PRAGMA user_version = 5")
        conn.commit()
        version = 5
    if version < 6:
        # Idempotent: DROP ... IF EXISTS makes a re-run over an
        # already-migrated (or fresh, chunk-table-less) db a no-op.
        conn.executescript(_SCHEMA_V6)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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


def mark_reflected(
    conn: sqlite3.Connection,
    path: Path,
    mtime: float | None = None,
    size: int | None = None,
    streaks: int | None = None,
    errors: int | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Stamp path as reflected. mtime/size default to a fresh path.stat()
    when not provided, but callers that captured stats earlier (e.g. at
    sweep gather-time) should pass them explicitly — otherwise a session
    that grows during a minutes-long batch gets stamped with its NEW
    (post-growth) stats and the appended tail is never reflected.

    streaks/errors/duration_seconds are optional session-level signal
    columns (M1 memory); callers that don't pass them leave the columns
    NULL, and existing sweep.py callers keep working unmodified."""
    if mtime is None or size is None:
        st = path.stat()
        mtime = st.st_mtime if mtime is None else mtime
        size = st.st_size if size is None else size
    conn.execute(
        """INSERT INTO sessions(path, mtime, size, reflected_at, streaks, errors, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
             mtime = excluded.mtime,
             size = excluded.size,
             reflected_at = excluded.reflected_at,
             streaks = excluded.streaks,
             errors = excluded.errors,
             duration_seconds = excluded.duration_seconds""",
        (str(path), mtime, size, _now(), streaks, errors, duration_seconds),
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
    # A fix-index entry literally named "novel" would otherwise collide
    # with dismissed/accepted novel rows under the merge-and-block logic
    # below — force novel semantics for that fix_id regardless of the
    # caller-supplied novel flag.
    novel = s.novel or s.fix_id == "novel"
    if not novel:
        blocked = conn.execute(
            "SELECT 1 FROM suggestions WHERE fix_id = ? "
            "AND status IN ('accepted', 'dismissed', 'adopted', 'lapsed')",
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
            1 if novel else 0,
            now,
            now,
        ),
    )
    conn.commit()


def expire_stale_pending(
    conn: sqlite3.Connection, now: datetime | None = None, days: int = 14
) -> list[int]:
    """Flip 'pending' suggestions untouched for >days to 'expired'.

    Expiry is "aged out undecided", NOT a verdict — it is deliberately
    excluded from the blocked statuses in blocked_fix_ids/record_suggestion,
    so a fix_id that recurs later with fresh evidence gets a legitimate new
    pending row (record_suggestion's merge path only matches status='pending'
    rows, so an expired row can never absorb it).
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    rows = conn.execute(
        "SELECT id FROM suggestions WHERE status = 'pending' AND updated_at < ?",
        (cutoff.isoformat(),),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        conn.executemany(
            "UPDATE suggestions SET status = 'expired', updated_at = ? WHERE id = ?",
            [(_now(), i) for i in ids],
        )
        conn.commit()
    return ids


def blocked_fix_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT fix_id FROM suggestions "
        "WHERE status IN ('accepted', 'dismissed', 'adopted', 'lapsed') AND novel = 0"
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


def mark_celebrated(conn: sqlite3.Connection, suggestion_id: int) -> bool:
    """Flip celebrated=1 for a suggestion (design doc: PROUD fires only
    while celebrated=0). Called by the pet after it has played the
    celebration animation once — idempotent, no-op on repeat calls."""
    cur = conn.execute(
        "UPDATE suggestions SET celebrated = 1 WHERE id = ?",
        (suggestion_id,),
    )
    conn.commit()
    return cur.rowcount > 0


LEDGER_SUMMARY_NOVEL_CAP = 10


def record_execution(
    conn: sqlite3.Connection,
    suggestion_id: int,
    fix_id: str,
    tier: int,
    detail: str,
    status: str,
    exit_code: int | None = None,
    output_head: str | None = None,
) -> int:
    """Audit-log one execution attempt (design doc Decision 3.3: everything
    is audited, including declines — a declined action is a signal). Both
    started_at and finished_at are stamped to now: callers record after the
    action has already run (or been declined), never mid-flight."""
    now = _now()
    cur = conn.execute(
        "INSERT INTO executions(suggestion_id, fix_id, tier, detail, "
        "started_at, finished_at, exit_code, output_head, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (suggestion_id, fix_id, tier, detail, now, now, exit_code, output_head, status),
    )
    conn.commit()
    return cur.lastrowid


def executions_for(conn: sqlite3.Connection, suggestion_id: int) -> list:
    return conn.execute(
        "SELECT * FROM executions WHERE suggestion_id = ? ORDER BY id",
        (suggestion_id,),
    ).fetchall()


def ledger_summary_for_prompt(conn: sqlite3.Connection) -> list[dict]:
    """Compact ledger view for the reflector prompt: fix_id + status +
    summary only — evidence stays out to keep the payload lean.

    Non-novel rows are kept in full (they're deduped by fix_id so the
    count stays bounded), but novel rows insert a fresh row every time
    and can grow without bound — cap them to the most recent
    LEDGER_SUMMARY_NOVEL_CAP so the ledger can't silently re-create the
    unbounded-prompt-growth failure mode it exists to prevent."""
    rows = conn.execute(
        "SELECT id, fix_id, status, blunt_summary, novel FROM suggestions ORDER BY id"
    ).fetchall()
    non_novel = [r for r in rows if not r["novel"]]
    novel = sorted((r for r in rows if r["novel"]), key=lambda r: r["id"], reverse=True)
    novel = novel[:LEDGER_SUMMARY_NOVEL_CAP]
    kept = non_novel + novel
    kept.sort(key=lambda r: r["id"])
    return [
        {"fix_id": r["fix_id"], "status": r["status"], "blunt_summary": r["blunt_summary"]}
        for r in kept
    ]


def current_character(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The most recently assigned character, or None if none has ever
    been recorded (a fresh install, before the first sweep runs)."""
    return conn.execute(
        "SELECT * FROM character_history ORDER BY id DESC LIMIT 1"
    ).fetchone()


def record_character(
    conn: sqlite3.Connection,
    character: str,
    reason: str,
    metrics_json: str,
    assigned_at: str | None = None,
) -> int:
    """Append a new character assignment. Every assignment — including
    the very first — gets its own row with a reason and a metrics
    snapshot, so the history is a full audit trail of who the pet has
    been, not just a mutable "current" pointer.

    assigned_at defaults to the real current time; callers that inject
    a synthetic `now` (character.py's evaluate/assign, and their tests)
    should pass its ISO form explicitly so stored tenure lines up with
    the clock they're testing against, not the wall clock."""
    cur = conn.execute(
        "INSERT INTO character_history(character, reason, metrics, assigned_at) "
        "VALUES (?, ?, ?, ?)",
        (character, reason, metrics_json, assigned_at or _now()),
    )
    conn.commit()
    return cur.lastrowid
