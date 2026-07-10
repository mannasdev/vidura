"""Memory retrieval — the ONLY read surface the future MCP server wraps.

FTS5/BM25 lexical retrieval behind a narrow interface (see
docs/design/m1-memory.md): friction vocabulary is highly lexical, and a
vector backend can replace the internals of search_chunks later without
touching any caller. Degrades to LIKE when FTS5 is unavailable.
Agents read; only Vidura writes (remember_chunks/prune are called by the
sweep only, never exposed via the context API).
"""

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from vidura.store import fts_available


@dataclass
class ChunkHit:
    chunk_id: int
    session_path: str
    text: str
    score: float
    created_at: str


def remember_chunks(
    conn: sqlite3.Connection,
    session_path: str,
    chunks: list[str],
    user_turns_per_chunk: list[int] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    turns = user_turns_per_chunk or [0] * len(chunks)
    conn.executemany(
        "INSERT INTO chunks(session_path, text, user_turns, created_at) VALUES (?, ?, ?, ?)",
        [(session_path, text, t, now) for text, t in zip(chunks, turns)],
    )
    conn.commit()


def _fts_query(terms: list[str]) -> str:
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms if t.strip()]
    return " OR ".join(quoted)


def search_chunks(
    conn: sqlite3.Connection,
    terms: list[str],
    k: int = 5,
    exclude_sessions: set[str] | None = None,
) -> list[ChunkHit]:
    query = _fts_query(terms)
    if not query:
        return []
    exclude = exclude_sessions or set()
    ordered_exclude = sorted(exclude)
    placeholders = ", ".join("?" for _ in ordered_exclude)
    exclusion_sql = f" AND c.session_path NOT IN ({placeholders})" if ordered_exclude else ""
    if fts_available(conn):
        rows = conn.execute(
            "SELECT c.id, c.session_path, c.text, bm25(chunks_fts) AS score, c.created_at "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            f"WHERE chunks_fts MATCH ?{exclusion_sql} ORDER BY score LIMIT ?",
            (query, *ordered_exclude, k),
        ).fetchall()
    else:
        print("vidura: FTS5 unavailable, LIKE fallback", file=sys.stderr)
        first = next((t for t in terms if t.strip()), None)
        if first is None:
            return []
        exclusion_sql_like = exclusion_sql.replace("c.session_path", "session_path")
        rows = conn.execute(
            "SELECT id, session_path, text, 0.0 AS score, created_at FROM chunks "
            f"WHERE text LIKE ?{exclusion_sql_like} ORDER BY id DESC LIMIT ?",
            (f"%{first}%", *ordered_exclude, k),
        ).fetchall()
    return [
        ChunkHit(r["id"], r["session_path"], r["text"], r["score"], r["created_at"])
        for r in rows
    ]


def prune_chunks(conn: sqlite3.Connection, days: int = 90) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = conn.execute("DELETE FROM chunks WHERE created_at < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def search_sessions(conn: sqlite3.Connection, terms: list[str], k: int = 10) -> list[tuple[str, float]]:
    hits = search_chunks(conn, terms, k=k * 4)
    best: dict[str, float] = {}
    for h in hits:
        if h.session_path not in best or h.score < best[h.session_path]:
            best[h.session_path] = h.score
    return sorted(best.items(), key=lambda kv: kv[1])[:k]


def get_context(conn: sqlite3.Connection, terms: list[str], token_budget: int) -> str:
    char_budget = token_budget * 4
    parts: list[str] = []
    used = 0
    for hit in search_chunks(conn, terms, k=20):
        snippet = hit.text[: max(0, char_budget - used)]
        if not snippet:
            break
        parts.append(snippet)
        used += len(snippet) + 2
        if used >= char_budget:
            break
    return "\n\n".join(parts)
