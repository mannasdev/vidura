"""Multi-pass (map-reduce) sweep: full-coverage friction reporting.

M0's single pass covered ~1% of the 30-day window. The sweep packs
friction sessions into payload-budget batches, reflects each, and
writes results to the ledger — which IS the reduce step (same-fix
suggestions merge; dismissed fixes never resurface). Sessions are
marked reflected only when their batch succeeds, so an interrupted
sweep (session limit, ctrl-C) resumes where it left off.
"""

import argparse
import contextlib
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from vidura.character import assign_character
from vidura.chunk import chunk_turns
from vidura.contract import CONTRACT_VERSION, PAYLOAD_BUDGET_CHARS, ReflectRequest
from vidura.fix_index import load_fix_index
from vidura.follow_through import evaluate_follow_through
from vidura.hooks_cli import _support_dir
from vidura.ingest import parse_session
from vidura.memory import memory_status, remember_chunks, search_chunks
from vidura.redact import redact
from vidura.reflect import reflect
from vidura.report import CLAUDE_PROJECTS_DIR, DEFAULT_WINDOW_DAYS, find_recent_sessions
from vidura.signals import extract_signals
from vidura.store import (
    _sanitize,
    current_character,
    expire_stale_pending,
    ledger_entries,
    ledger_summary_for_prompt,
    mark_reflected,
    needs_reflection,
    open_db,
    record_suggestion,
)

PER_SESSION_CHUNK_BUDGET = 24000
DEFAULT_MAX_BATCHES = 20

# Process-level single-chokepoint lock: 3 independent OS processes can
# invoke a sweep concurrently (the pet's own 30-min ambient sweep, which
# calls vidura-sweep directly — bypassing hooks_cli entirely; the
# SessionEnd hook's detached sweep; and a manual/interactive vidura-sweep
# run). This is a SEPARATE lockfile from hooks_cli's sweep.lock —
# hooks_cli's lock only dedups hook-triggered SPAWNS (so a burst of
# SessionEnd events doesn't queue up N sweep processes); this lock is
# the actual mutex around doing sweep work at all, regardless of which
# of the 3 callers is doing it. Keeping them separate avoids a
# double-lock deadlock: hooks_cli writes+holds its own lock for the
# lifetime of the spawned subprocess (cleared by a bash trap on exit),
# so if run_sweep tried to acquire THAT same file it would always see
# its own parent's lock and refuse to run.
_SWEEP_RUN_LOCK_NAME = "sweep-run.lock"
SWEEP_RUN_LOCK_STALE_SECONDS = 45 * 60


def _sweep_run_lock_path() -> Path:
    return _support_dir() / _SWEEP_RUN_LOCK_NAME


@contextlib.contextmanager
def _sweep_run_lock():
    """O_EXCL lockfile: the single chokepoint serializing sweep work
    across all 3 concurrent callers (pet ambient sweep, hook-spawned
    sweep, interactive CLI). A second concurrent sweep sees the lock
    already held and yields False (never blocks/retries) — sweeps are
    resume-safe by design (sessions are only marked reflected batch by
    batch), so skipping this run entirely is correct, not lossy: the
    next sweep picks up exactly where the skipped one would have
    started. A stale lock (holder crashed without cleanup) is treated
    as absent after SWEEP_RUN_LOCK_STALE_SECONDS."""
    lock_path = _sweep_run_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mtime = lock_path.stat().st_mtime
        if (time.time() - mtime) >= SWEEP_RUN_LOCK_STALE_SECONDS:
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()
    except FileNotFoundError:
        pass

    fd = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(time.time()).encode())
        os.close(fd)
        fd = None
        yield True
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


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
    # Judge-visibility only (see signals.SessionSignals.tool_error_repeats)
    # — never feeds streak_count/error_count, which are the columns
    # mark_reflected stamps into sessions.errors and character.py reads
    # for the robot threshold.
    tool_error_repeats: dict[str, int] = field(default_factory=dict)


def gather_pending_work(
    conn,
    root: Path = CLAUDE_PROJECTS_DIR,
    window_days: int = DEFAULT_WINDOW_DAYS,
    rescan: bool = False,
) -> list[SessionWork]:
    """rescan=True ignores seen-marks: already-reflected sessions are
    re-judged. Use after the fix index grows — old sessions were judged
    against the old, smaller index. Ledger dedup/blocking still applies,
    so a rescan can only add new findings, never repeat resolved ones."""
    work: list[SessionWork] = []
    for path in find_recent_sessions(root=root, window_days=window_days):
        if not rescan and not needs_reflection(conn, path):
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
            # No friction signal: mark reflected with zero stats instead
            # of leaving it unmarked. Previously this session would be
            # re-parsed and re-redacted on EVERY future sweep forever
            # (outside-voice finding #8) — quiet sessions never earned a
            # sessions-table row, so the steady-state rescan cost only
            # grew. Consequence (also see docs/design/system-review-
            # 2026-07-11.md): sessions/character/mood metrics now measure
            # ALL sessions in the window, not just friction sessions —
            # character.py's n_sessions/sessions_per_day denominators
            # widen accordingly, which is the intended de-bias (outside-
            # voice finding #4). It contributes no chunks/batches.
            mark_reflected(conn, path, mtime=st.st_mtime, size=st.st_size, streaks=0, errors=0, duration_seconds=0.0)
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
                tool_error_repeats=dict(signals.tool_error_repeats),
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

    # tool_error_repeats: judge-visibility only (see SessionWork/
    # SessionSignals docstrings) — merged across the batch and capped at
    # the top 20 by count, mirroring report.py's error_repeats capping.
    batch_tool_error_repeats: dict[str, int] = {}
    for w in batch:
        for key, count in w.tool_error_repeats.items():
            batch_tool_error_repeats[key] = batch_tool_error_repeats.get(key, 0) + count
    top_tool_error_repeats = dict(
        sorted(batch_tool_error_repeats.items(), key=lambda kv: kv[1], reverse=True)[:20]
    )

    return ReflectRequest(
        contract_version=CONTRACT_VERSION,
        signals={
            "sessions_in_batch": len(batch),
            "reprompt_streaks_in_batch": sum(w.streak_count for w in batch),
            "tool_error_repeats": top_tool_error_repeats,
        },
        chunks=chunks,
        fix_index=fix_index_dicts,
        ledger=ledger_summary_for_prompt(conn),
        similar_past_friction=similar_past_friction,
    )


def run_sweep(
    conn,
    batches: list[list[SessionWork]],
    max_batches: int | None = None,
) -> dict:
    stats = {"batches_run": 0, "batches_failed": 0, "sessions_reflected": 0, "suggestions_recorded": 0}
    selected = batches if max_batches is None else batches[:max_batches]
    for i, batch in enumerate(selected, start=1):
        request = _batch_request(conn, batch)
        try:
            response = reflect(request)
            for suggestion in response.suggestions:
                record_suggestion(conn, suggestion)
                stats["suggestions_recorded"] += 1
            for w in batch:
                # Order matters for resume correctness: remember before
                # mark. remember_chunks is idempotent per session_path
                # (delete-then-insert), so a re-run after a crash between
                # these two writes just re-remembers safely. The reverse
                # order could mark a session reflected whose chunks were
                # never stored, and resume would then skip it forever.
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


def _maybe_report_character_evolution(conn) -> None:
    """Assign the pet's character for this run and, if it changed
    (stickiness-permitting), tell the user on stderr — this is a status
    line, not the ledger report, so it never touches stdout."""
    before = current_character(conn)
    before_name = before["character"] if before is not None else None
    result = assign_character(conn)
    if result["character"] != before_name:
        old = before_name or "face"
        print(
            f"vidura sweep: your pet evolved — {old} -> {result['character']} ({result['reason']})",
            file=sys.stderr,
        )


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
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="re-judge already-reflected sessions (use after the fix index grows; costs a full sweep)",
    )
    args = parser.parse_args(argv)

    with _sweep_run_lock() as acquired:
        if not acquired:
            print("vidura sweep: another sweep is running", file=sys.stderr)
            return 0

        conn = open_db()
        try:
            print(f"vidura sweep: memory {memory_status()}", file=sys.stderr)
            expired = expire_stale_pending(conn)
            if expired:
                print(
                    f"vidura sweep: expired {len(expired)} stale pending suggestion(s) "
                    "(older than 14 days undecided)",
                    file=sys.stderr,
                )
            work = gather_pending_work(conn, root=CLAUDE_PROJECTS_DIR, window_days=args.window_days, rescan=args.rescan)
            if not work:
                print("Nothing new to sweep — all friction sessions already reflected.")
                _maybe_report_character_evolution(conn)
                _print_ledger_report(conn)
                return 0
            batches = pack_batches(work)
            max_batches = None if args.full else args.batches
            stats = run_sweep(conn, batches, max_batches=max_batches)
            print(
                f"Sweep: {stats['batches_run']} batches run, {stats['batches_failed']} failed, "
                f"{stats['sessions_reflected']} sessions reflected, "
                f"{stats['suggestions_recorded']} suggestions recorded.\n"
            )
            for _suggestion_id, fix_id, verdict in evaluate_follow_through(conn):
                if verdict == "adopted":
                    print(f"Follow-through: [{fix_id}] adopted — behavior changed since you accepted it.")
                elif verdict == "lapsed":
                    print(f"Follow-through: [{fix_id}] lapsed — accepted 2+ weeks ago, behavior unchanged.")
            _maybe_report_character_evolution(conn)
            _print_ledger_report(conn)
            return 0
        finally:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
