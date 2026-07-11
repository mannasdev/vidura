"""Memory retrieval — the ONLY read surface the future MCP server wraps.

Supermemory is THE memory layer (docs/design/supermemory-adoption.md) —
one memory system, not two: no homegrown FTS5 index alongside it.
`SUPERMEMORY_CC_API_KEY` set turns memory on; unset, Vidura runs
memory-less — remember_chunks no-ops and
search_chunks returns [] — exactly like M0. Agents read; only Vidura
writes (remember_chunks/search_chunks are called by the sweep and the
reflector's retrieval step, never exposed via a write-capable API).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os.path import basename
from urllib.parse import urlparse

SUPERMEMORY_CONTAINER_TAG = "vidura"
SUPERMEMORY_TIMEOUT_SECONDS = 5
SUPERMEMORY_DEFAULT_URL = "http://localhost:6767"
MEMORY_RETENTION_DAYS = 90

_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class ChunkHit:
    chunk_id: int
    session_path: str
    text: str
    score: float
    created_at: str


# --- circuit breaker (module-level: process-lifetime state) ---
#
# Trips on the first request failure/timeout, OR once cumulative
# supermemory wall-time in this process exceeds 30s. Once tripped, all
# calls skip instantly — exactly one stderr note is ever printed.
#
# This budget is PER-PROCESS, not global: the pet's ambient sweep, the
# SessionEnd hook's detached sweep, and an interactive CLI invocation
# are 3 independent OS processes, each with its own module-level
# _cumulative_wall_time. Worst case, a slow-but-not-failing supermemory
# endpoint can burn up to 3x BREAKER_WALL_TIME_BUDGET_SECONDS of real
# wall-time across the topology before every process has independently
# tripped its own breaker. Accepted: making the breaker process-shared
# would need its own cross-process coordination (a file, a socket) for
# a budget whose entire purpose is bounding worst-case latency, not
# correctness — not worth the complexity at this scale.

BREAKER_WALL_TIME_BUDGET_SECONDS = 30.0

_breaker_tripped = False
_breaker_reason: str | None = None
_cumulative_wall_time = 0.0
_breaker_note_printed = False


def _reset_breaker_for_tests() -> None:
    """Test-only helper: module-level breaker state otherwise leaks
    across tests since it's process-lifetime by design."""
    global _breaker_tripped, _breaker_reason, _cumulative_wall_time, _breaker_note_printed
    _breaker_tripped = False
    _breaker_reason = None
    _cumulative_wall_time = 0.0
    _breaker_note_printed = False


def _trip_breaker(reason: str) -> None:
    global _breaker_tripped, _breaker_reason, _breaker_note_printed
    _breaker_tripped = True
    _breaker_reason = reason
    if not _breaker_note_printed:
        print(f"vidura: supermemory circuit breaker tripped ({reason}); memory disabled for this run", file=sys.stderr)
        _breaker_note_printed = True


def breaker_tripped() -> bool:
    return _breaker_tripped


# --- activation + remote gate ---

_remote_gate_note_printed = False


def _is_local_host(url: str) -> bool:
    host = urlparse(url).hostname
    return host in _LOCALHOST_HOSTS


def _supermemory_config() -> tuple[str, str] | None:
    """(base_url, api_key) if SUPERMEMORY_CC_API_KEY is set and the
    remote gate + circuit breaker both allow it, else None.

    Remote-URL hard gate: a non-localhost VIDURA_SUPERMEMORY_URL requires
    VIDURA_SUPERMEMORY_ALLOW_REMOTE=1, else memory disables for the
    process with exactly one stderr line — detached sweeps make ordinary
    warnings invisible, so a gate is the only observable control.
    """
    global _remote_gate_note_printed
    api_key = os.environ.get("SUPERMEMORY_CC_API_KEY")
    if not api_key:
        return None
    if _breaker_tripped:
        return None
    url = os.environ.get("VIDURA_SUPERMEMORY_URL", SUPERMEMORY_DEFAULT_URL)
    if not _is_local_host(url) and os.environ.get("VIDURA_SUPERMEMORY_ALLOW_REMOTE") != "1":
        if not _remote_gate_note_printed:
            print(
                f"vidura: VIDURA_SUPERMEMORY_URL ({url}) is not localhost and "
                "VIDURA_SUPERMEMORY_ALLOW_REMOTE!=1; memory disabled for this run",
                file=sys.stderr,
            )
            _remote_gate_note_printed = True
        return None
    return (url, api_key)


def memory_status() -> str:
    """One-word status for diagnosability: off / active / breaker-tripped."""
    if _breaker_tripped:
        return "breaker-tripped"
    if _supermemory_config() is not None:
        return "active"
    return "off"


def _supermemory_request(cfg: tuple[str, str], method: str, path: str, body: dict | None = None) -> dict:
    url, api_key = cfg
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=SUPERMEMORY_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    finally:
        global _cumulative_wall_time
        _cumulative_wall_time += time.monotonic() - start
        if _cumulative_wall_time > BREAKER_WALL_TIME_BUDGET_SECONDS and not _breaker_tripped:
            _trip_breaker(f"cumulative supermemory wall-time exceeded {BREAKER_WALL_TIME_BUDGET_SECONDS}s")


def _supermemory_push(cfg: tuple[str, str], session_basename: str, chunks: list[str], now: str) -> None:
    # Best-effort: never let a supermemory outage break remember_chunks.
    # Idempotent re-push: list docs scoped by BOTH containerTag and
    # session_basename (the tag conjunct is mandatory — listing by
    # basename alone on a shared server could bulk-delete another app's
    # docs that happen to reuse the same session filename).
    try:
        existing = _supermemory_request(
            cfg,
            "POST",
            "/v3/documents/list",
            {
                "filters": {
                    "AND": [
                        {"filterType": "metadata", "key": "session_basename", "value": session_basename},
                    ]
                },
                "containerTags": [SUPERMEMORY_CONTAINER_TAG],
            },
        )
        ids = [m["id"] for m in existing.get("memories", [])]
        if ids:
            _supermemory_request(cfg, "DELETE", "/v3/documents/bulk", {"ids": ids})
        for i, text in enumerate(chunks):
            _supermemory_request(
                cfg,
                "POST",
                "/v3/documents",
                {
                    "content": text,
                    "containerTag": SUPERMEMORY_CONTAINER_TAG,
                    "metadata": {
                        "session_basename": session_basename,
                        "chunk_index": i,
                        "created_at": now,
                    },
                    "taskType": "memory",
                },
            )
    except Exception as exc:
        if not _breaker_tripped:
            _trip_breaker(f"request failed ({exc})")


def _supermemory_search(cfg: tuple[str, str], terms: list[str], k: int, exclude_basenames: set[str]) -> list[ChunkHit]:
    try:
        response = _supermemory_request(
            cfg,
            "POST",
            "/v3/search",
            # containerTags MUST be plural here: the live server's /v3/search
            # silently returns zero results for a singular "containerTag" key
            # (no error) — verified against supermemory-local, 2026-07-11.
            {"containerTags": [SUPERMEMORY_CONTAINER_TAG], "q": " ".join(terms)},
        )
    except Exception as exc:
        if not _breaker_tripped:
            _trip_breaker(f"request failed ({exc})")
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MEMORY_RETENTION_DAYS)
    hits: list[ChunkHit] = []
    for result in response.get("results", []):
        metadata = result.get("metadata") or {}
        session_basename = metadata.get("session_basename")
        if not session_basename or session_basename in exclude_basenames:
            continue
        created_at = metadata.get("created_at")
        if not created_at:
            continue  # missing created_at -> dropped (read-side age filter)
        try:
            created_dt = datetime.fromisoformat(created_at)
            stale = created_dt < cutoff
        except (ValueError, TypeError):
            # TypeError: a naive (timezone-less) created_at can't compare
            # with the aware cutoff — treat unparseable/incomparable
            # timestamps as unverifiable and drop, same as missing.
            continue
        if stale:
            continue  # older than the retention window -> dropped
        for chunk in result.get("chunks", []):
            hits.append(
                ChunkHit(
                    chunk_id=-1,
                    session_path=session_basename,
                    text=chunk.get("content", ""),
                    score=result.get("score", 0.0),
                    created_at=created_at,
                )
            )
    # Higher-is-better similarity score (supermemory), single scale.
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def remember_chunks(
    session_path: str,
    chunks: list[str],
    user_turns_per_chunk: list[int] | None = None,
) -> None:
    """Push redacted chunk text to supermemory. Silently no-ops when
    memory is off (no key, remote-gated, or breaker-tripped). Chunks
    live entirely in supermemory now, not SQLite, so there's no `conn`
    to thread through here."""
    cfg = _supermemory_config()
    if cfg is None or not chunks:
        return
    now = datetime.now(timezone.utc).isoformat()
    _supermemory_push(cfg, basename(session_path), chunks, now)


def search_chunks(
    terms: list[str],
    k: int = 5,
    exclude_sessions: set[str] | None = None,
) -> list[ChunkHit]:
    """Search supermemory. Returns [] when memory is off — no stderr
    spam, that's the memory-less-mode contract."""
    query_terms = [t for t in terms if t.strip()]
    if not query_terms:
        return []
    cfg = _supermemory_config()
    if cfg is None:
        return []
    exclude = exclude_sessions or set()
    exclude_basenames = {basename(p) for p in exclude}
    return _supermemory_search(cfg, query_terms, k=k, exclude_basenames=exclude_basenames)


def search_sessions(terms: list[str], k: int = 10) -> list[tuple[str, float]]:
    """Best-scoring session per basename, single scale (supermemory
    similarity, higher-better) — sorted descending."""
    hits = search_chunks(terms, k=k * 4)
    best: dict[str, float] = {}
    for h in hits:
        if h.session_path not in best or h.score > best[h.session_path]:
            best[h.session_path] = h.score
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:k]


def get_context(terms: list[str], token_budget: int) -> str:
    char_budget = token_budget * 4
    parts: list[str] = []
    used = 0
    for hit in search_chunks(terms, k=20):
        snippet = hit.text[: max(0, char_budget - used)]
        if not snippet:
            break
        parts.append(snippet)
        used += len(snippet) + 2
        if used >= char_budget:
            break
    return "\n\n".join(parts)
