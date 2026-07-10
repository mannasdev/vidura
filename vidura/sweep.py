"""Multi-pass (map-reduce) sweep: full-coverage friction reporting.

M0's single pass covered ~1% of the 30-day window. The sweep packs
friction sessions into payload-budget batches, reflects each, and
writes results to the ledger — which IS the reduce step (same-fix
suggestions merge; dismissed fixes never resurface). Sessions are
marked reflected only when their batch succeeds, so an interrupted
sweep (session limit, ctrl-C) resumes where it left off.
"""

from dataclasses import dataclass
from pathlib import Path

from vidura.chunk import chunk_turns
from vidura.contract import PAYLOAD_BUDGET_CHARS
from vidura.ingest import parse_session
from vidura.redact import redact
from vidura.report import CLAUDE_PROJECTS_DIR, DEFAULT_WINDOW_DAYS, find_recent_sessions
from vidura.signals import extract_signals
from vidura.store import needs_reflection

PER_SESSION_CHUNK_BUDGET = 24000


@dataclass
class SessionWork:
    path: Path
    chunks: list[str]
    streak_count: int


def gather_pending_work(
    conn,
    root: Path = CLAUDE_PROJECTS_DIR,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[SessionWork]:
    work: list[SessionWork] = []
    for path in find_recent_sessions(root=root, window_days=window_days):
        if not needs_reflection(conn, path):
            continue
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
            SessionWork(path=path, chunks=kept, streak_count=len(signals.reprompt_streaks))
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
