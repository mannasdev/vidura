"""Multi-pass (map-reduce) sweep: full-coverage friction reporting.

M0's single pass covered ~1% of the 30-day window. The sweep packs
friction sessions into payload-budget batches, reflects each, and
writes results to the ledger — which IS the reduce step (same-fix
suggestions merge; dismissed fixes never resurface). Sessions are
marked reflected only when their batch succeeds, so an interrupted
sweep (session limit, ctrl-C) resumes where it left off.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from vidura.chunk import chunk_turns
from vidura.contract import CONTRACT_VERSION, PAYLOAD_BUDGET_CHARS, ReflectRequest
from vidura.fix_index import load_fix_index
from vidura.ingest import parse_session
from vidura.memory import prune_chunks, remember_chunks, search_chunks
from vidura.redact import redact
from vidura.reflect import reflect
from vidura.report import CLAUDE_PROJECTS_DIR, DEFAULT_WINDOW_DAYS, find_recent_sessions
from vidura.signals import extract_signals
from vidura.store import (
    _sanitize,
    ledger_entries,
    ledger_summary_for_prompt,
    mark_reflected,
    needs_reflection,
    open_db,
    record_suggestion,
)

PER_SESSION_CHUNK_BUDGET = 24000
DEFAULT_MAX_BATCHES = 20


@dataclass
class SessionWork:
    path: Path
    chunks: list[str]
    streak_count: int
    mtime: float = 0.0
    size: int = 0
    error_keys: list[str] = field(default_factory=list)
    error_count: int = 0
    duration_seconds: float = 0.0


def gather_pending_work(
    conn,
    root: Path = CLAUDE_PROJECTS_DIR,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[SessionWork]:
    work: list[SessionWork] = []
    for path in find_recent_sessions(root=root, window_days=window_days):
        if not needs_reflection(conn, path):
            continue
        # Capture stats once, here, at gather time. A session can grow
        # during a minutes-long batch; stamping it with stats read later
        # (at mark-time) would record the NEW mtime/size and the
        # appended tail would never be reflected.
        st = path.stat()
        turns = list(parse_session(path))
        if not turns:
            continue
        for turn in turns:
            turn.text = redact(turn.text)
        signals = extract_signals(turns)
        if not (signals.reprompt_streaks or signals.error_repeats):
            continue
        chunks = [c.text for c in chunk_turns(turns)]
        # keep the densest chunks up to the per-session budget so one
        # marathon session can't monopolize a whole batch
        chunks.sort(key=lambda t: t.count("[user]"), reverse=True)
        kept: list[str] = []
        total = 0
        for chunk in chunks:
            if total + len(chunk) > PER_SESSION_CHUNK_BUDGET and kept:
                break
            kept.append(chunk)
            total += len(chunk)
        work.append(
            SessionWork(
                path=path,
                chunks=kept,
                streak_count=len(signals.reprompt_streaks),
                mtime=st.st_mtime,
                size=st.st_size,
                error_keys=list(signals.error_repeats.keys()),
                error_count=sum(signals.error_repeats.values()),
                duration_seconds=signals.duration_seconds or 0.0,
            )
        )
    return work


def pack_batches(work: list[SessionWork], budget_chars: int = PAYLOAD_BUDGET_CHARS) -> list[list[SessionWork]]:
    """Greedy whole-session packing, densest sessions first. A session
    never splits across batches — that keeps mark_reflected atomic per
    batch, which is what makes resume correct."""
    ordered = sorted(work, key=lambda w: w.streak_count, reverse=True)
    batches: list[list[SessionWork]] = []
    current: list[SessionWork] = []
    current_chars = 0
    for w in ordered:
        w_chars = sum(len(c) for c in w.chunks)
        if current and current_chars + w_chars > budget_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(w)
        current_chars += w_chars
    if current:
        batches.append(current)
    return batches


def _batch_request(conn, batch: list[SessionWork]) -> ReflectRequest:
    chunks = [c for w in batch for c in w.chunks]
    fix_index_dicts = [
        {
            "id": f.id,
            "title": f.title,
            "friction_patterns": f.friction_patterns,
            "remedy": f.remedy,
            "confidence_floor": f.confidence_floor,
        }
        for f in load_fix_index()
    ]
    # Retrieval: pull similar past friction for the errors seen in this
    # batch. Capped at 8 terms and k=3 hits, each snippet truncated to
    # 1500 chars — 3x1500 rides inside the 16k-token context headroom
    # (48k chunks + scaffolding measured well under) without displacing
    # this batch's own chunks.
    terms: list[str] = []
    for w in batch:
        for key in w.error_keys:
            if key not in terms:
                terms.append(key)
    terms = terms[:8]
    similar_past_friction: list[str] = []
    if terms:
        hits = search_chunks(conn, terms, k=3, exclude_sessions={str(w.path) for w in batch})
        similar_past_friction = [h.text[:1500] for h in hits]
    return ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={
            "sessions_in_batch": len(batch),
            "reprompt_streaks_in_batch": sum(w.streak_count for w in batch),
        },
        chunks=chunks,
        fix_index=fix_index_dicts,
        ledger=ledger_summary_for_prompt(conn),
        similar_past_friction=similar_past_friction,
    )


def run_sweep(
    conn,
    batches: list[list[SessionWork]],
    backend: str = "auto",
    max_batches: int | None = None,
) -> dict:
    stats = {"batches_run": 0, "batches_failed": 0, "sessions_reflected": 0, "suggestions_recorded": 0}
    selected = batches if max_batches is None else batches[:max_batches]
    for i, batch in enumerate(selected, start=1):
        request = _batch_request(conn, batch)
        try:
            response = reflect(request, backend=backend)
            for suggestion in response.suggestions:
                record_suggestion(conn, suggestion)
                stats["suggestions_recorded"] += 1
            for w in batch:
                remember_chunks(conn, str(w.path), w.chunks)
                mark_reflected(
                    conn,
                    w.path,
                    mtime=w.mtime,
                    size=w.size,
                    streaks=w.streak_count,
                    errors=w.error_count,
                    duration_seconds=w.duration_seconds,
                )
                stats["sessions_reflected"] += 1
        except Exception as exc:
            # Same silence principle as the report: a failed batch is
            # skipped and logged; its sessions stay unmarked so the next
            # sweep resumes exactly here. Widened to cover the
            # record_suggestion/mark_reflected loops too — a locked db or
            # a session file deleted mid-sweep (FileNotFoundError from
            # mark_reflected's stat) must not abort the whole sweep,
            # just this batch.
            print(f"vidura sweep: batch {i}/{len(selected)} failed, will retry next run: {exc}", file=sys.stderr)
            stats["batches_failed"] += 1
            continue
        stats["batches_run"] += 1
        print(f"vidura sweep: batch {i}/{len(selected)} done ({len(batch)} sessions)", file=sys.stderr)
    return stats


def _print_ledger_report(conn) -> None:
    pending = ledger_entries(conn, status="pending")
    if not pending:
        print("No pending suggestions — nothing cleared the bar. Silence is correct.")
        return
    print(f"Vidura friction report — {len(pending)} pending suggestion(s)\n")
    for row in pending:
        print(f"[{row['id']}] [{row['fix_id']}] confidence={row['confidence']:.2f} seen_in={row['occurrences']} batch(es)")
        print(f"    {_sanitize(row['blunt_summary'])}")
        import json as _json
        for quote in _json.loads(row["evidence"]):
            print(f"      > {_sanitize(quote)}")
        print()
    print("Accept/dismiss with: vidura-ledger accept <id> | vidura-ledger dismiss <id>")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidura-sweep")
    parser.add_argument("--full", action="store_true", help=f"run all batches (default: top {DEFAULT_MAX_BATCHES} densest)")
    parser.add_argument("--batches", type=int, default=DEFAULT_MAX_BATCHES)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--backend", choices=["auto", "claude", "ollama"], default=os.environ.get("VIDURA_REFLECTOR_BACKEND", "auto"))
    args = parser.parse_args(argv)

    conn = open_db()
    try:
        pruned = prune_chunks(conn)
        if pruned:
            print(f"vidura sweep: pruned {pruned} chunks older than 90 days", file=sys.stderr)
        work = gather_pending_work(conn, root=CLAUDE_PROJECTS_DIR, window_days=args.window_days)
        if not work:
            print("Nothing new to sweep — all friction sessions already reflected.")
            _print_ledger_report(conn)
            return 0
        batches = pack_batches(work)
        max_batches = None if args.full else args.batches
        stats = run_sweep(conn, batches, backend=args.backend, max_batches=max_batches)
        print(
            f"Sweep: {stats['batches_run']} batches run, {stats['batches_failed']} failed, "
            f"{stats['sessions_reflected']} sessions reflected, "
            f"{stats['suggestions_recorded']} suggestions recorded.\n"
        )
        _print_ledger_report(conn)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
