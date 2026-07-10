"""Memory retrieval — the ONLY read surface the future MCP server wraps.

FTS5/BM25 lexical retrieval behind a narrow interface (see
docs/design/m1-memory.md): friction vocabulary is highly lexical, and a
vector backend can replace the internals of search_chunks later without
touching any caller. Degrades to LIKE when FTS5 is unavailable.
Agents read; only Vidura writes (remember_chunks/prune are called by the
sweep only, never exposed via the context API).
"""

import json
import os
import sqlite3
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from vidura.store import fts_available

SUPERMEMORY_CONTAINER_TAG = "vidura"
SUPERMEMORY_TIMEOUT_SECONDS = 5


@dataclass
class ChunkHit:
    chunk_id: int
    session_path: str
    text: str
    score: float
    created_at: str


def _supermemory_config() -> tuple[str, str] | None:
    """(base_url, api_key) if VIDURA_MEMORY_BACKEND=blend and a key is set, else None."""
    if os.environ.get("VIDURA_MEMORY_BACKEND") != "blend":
        return None
    api_key = os.environ.get("SUPERMEMORY_CC_API_KEY")
    if not api_key:
        return None
    url = os.environ.get("VIDURA_SUPERMEMORY_URL", "http://localhost:6767")
    return (url, api_key)


def _supermemory_request(cfg: tuple[str, str], method: str, path: str, body: dict | None = None) -> dict:
    url, api_key = cfg
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=SUPERMEMORY_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _supermemory_push(cfg: tuple[str, str], session_path: str, chunks: list[str], now: str) -> None:
    # Best-effort mirror to the external store: never let a supermemory
    # outage break remember_chunks (the local FTS5 write already happened).
    try:
        existing = _supermemory_request(
            cfg,
            "POST",
            "/v3/documents/list",
            {"filters": {"AND": [{"filterType": "metadata", "key": "session_path", "value": session_path}]}},
        )
        ids = [m["id"] for m in existing.get("memories", [])]
        if ids:
            _supermemory_request(cfg, "DELETE", "/v3/documents/bulk", {"ids": ids})
        for text in chunks:
            _supermemory_request(
                cfg,
                "POST",
                "/v3/documents",
                {
                    "content": text,
                    "containerTag": SUPERMEMORY_CONTAINER_TAG,
                    "metadata": {"session_path": session_path, "created_at": now},
                    "taskType": "memory",
                },
            )
    except Exception as exc:
        print(f"vidura: supermemory push failed, continuing FTS5-only ({exc})", file=sys.stderr)


def _supermemory_search(cfg: tuple[str, str], terms: list[str], k: int, exclude_sessions: set[str]) -> list[ChunkHit]:
    # Best-effort: any failure here just means search_chunks falls back to
    # its FTS5 results, same contract as _supermemory_push.
    try:
        response = _supermemory_request(
            cfg,
            "POST",
            "/v3/search",
            {"containerTag": SUPERMEMORY_CONTAINER_TAG, "q": " ".join(terms)},
        )
    except Exception as exc:
        print(f"vidura: supermemory search failed, continuing FTS5-only ({exc})", file=sys.stderr)
        return []
    hits: list[ChunkHit] = []
    for result in response.get("results", []):
        metadata = result.get("metadata") or {}
        session_path = metadata.get("session_path")
        if not session_path or session_path in exclude_sessions:
            continue
        for chunk in result.get("chunks", []):
            hits.append(
                ChunkHit(
                    chunk_id=-1,
                    session_path=session_path,
                    text=chunk.get("content", ""),
                    score=result.get("score", 0.0),
                    created_at=metadata.get("created_at", ""),
                )
            )
    return hits[:k]


def remember_chunks(
    conn: sqlite3.Connection,
    session_path: str,
    chunks: list[str],
    user_turns_per_chunk: list[int] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    turns = user_turns_per_chunk or [0] * len(chunks)
    # Delete-then-insert in one transaction so a resumed sweep re-running
    # remember_chunks for a session already stored is idempotent (no
    # unique constraint on session_path means a naive append would
    # duplicate chunks). The chunks_ad trigger cleans the FTS index too.
    conn.execute("DELETE FROM chunks WHERE session_path = ?", (session_path,))
    conn.executemany(
        "INSERT INTO chunks(session_path, text, user_turns, created_at) VALUES (?, ?, ?, ?)",
        [(session_path, text, t, now) for text, t in zip(chunks, turns)],
    )
    conn.commit()
    cfg = _supermemory_config()
    if cfg is not None and chunks:
        _supermemory_push(cfg, session_path, chunks, now)


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
    fts_hits = [
        ChunkHit(r["id"], r["session_path"], r["text"], r["score"], r["created_at"])
        for r in rows
    ]
    cfg = _supermemory_config()
    if cfg is None:
        return fts_hits
    seen = {(h.session_path, h.text) for h in fts_hits}
    merged = list(fts_hits)
    for hit in _supermemory_search(cfg, terms, k=k, exclude_sessions=exclude):
        identity = (hit.session_path, hit.text)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(hit)
        if len(merged) >= k:
            break
    return merged[:k]


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
