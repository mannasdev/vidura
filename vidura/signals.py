"""Cheap structural friction signals — no model call needed.

Mirrors the original spec's Ingestor signal list: re-prompt streaks
(consecutive user turns with no intervening tool use), error loops
(same error string 3+ times), session duration, and models used.
"""

from dataclasses import dataclass
from datetime import datetime

from vidura.ingest import Turn

ERROR_MARKERS = ("Error:", "Traceback", "Exception:", "failed:")


@dataclass
class SessionSignals:
    reprompt_streaks: list[int]
    error_repeats: dict[str, int]
    duration_seconds: float | None
    models_used: list[str]
    turn_count: int
    # Errors seen inside tool_result turns (e.g. a traceback in command
    # output) — counted the same way as error_repeats (ERROR_MARKERS,
    # _error_key, 3+ threshold) but kept in a SEPARATE field on purpose.
    # This is judge-visibility only: unlike error_repeats it must never
    # gate session inclusion (sweep.py's has_friction stays
    # streaks-or-error_repeats) and must never feed character.py's robot
    # threshold or mood — tool output is machine noise (retry loops,
    # verbose build/test spam) and folding it into the same signal that
    # drives inclusion/character would re-import exactly the kind of
    # noise is_tool_result was introduced to keep out of the streak count.
    tool_error_repeats: dict[str, int] = None  # type: ignore[assignment]
    # Per-session tool-usage counts: tool name (e.g. "Read", or an
    # MCP-style "mcp__playwright__click") -> number of tool_use calls in
    # this session. Cheap, deterministic — the substrate follow_through.py
    # reads to tell whether an installed tool is actually getting used
    # (adoption_tool matching is a case-insensitive substring match
    # against these keys, so "playwright" matches
    # "mcp__playwright__click"). Never gates inclusion or feeds
    # character.py, same posture as tool_error_repeats.
    tools_used: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tool_error_repeats is None:
            self.tool_error_repeats = {}
        if self.tools_used is None:
            self.tools_used = {}


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _error_key(text: str, marker: str) -> str:
    idx = text.find(marker)
    return text[idx: idx + 80].strip()


def extract_signals(turns: list[Turn]) -> SessionSignals:
    reprompt_streaks: list[int] = []
    current_streak = 0
    error_counts: dict[str, int] = {}
    tool_error_counts: dict[str, int] = {}
    tool_use_counts: dict[str, int] = {}
    models: set[str] = set()
    timestamps: list[datetime] = []

    for turn in turns:
        ts = _parse_ts(turn.timestamp)
        if ts is not None:
            timestamps.append(ts)
        if turn.model:
            models.add(turn.model)

        if turn.type == "user":
            # Tool results arrive as user-type records but are not human
            # prompts — counting them inflated streaks with machine noise
            # (observed in M0). They are transparent to the streak.
            if not turn.is_tool_result:
                current_streak += 1
            elif turn.is_tool_result:
                # ERROR_MARKERS scanning previously only ran on assistant
                # turns, blind to tracebacks that arrive as tool_result
                # content (e.g. a failing test's stderr echoed back by
                # the tool). Counted into a SEPARATE dict — see
                # SessionSignals.tool_error_repeats docstring for why
                # this must not merge into error_counts.
                for marker in ERROR_MARKERS:
                    if marker in turn.text:
                        key = _error_key(turn.text, marker)
                        tool_error_counts[key] = tool_error_counts.get(key, 0) + 1
        elif turn.type == "assistant":
            if turn.tool_use:
                if current_streak >= 2:
                    reprompt_streaks.append(current_streak)
                current_streak = 0
            for marker in ERROR_MARKERS:
                if marker in turn.text:
                    key = _error_key(turn.text, marker)
                    error_counts[key] = error_counts.get(key, 0) + 1
            for name in turn.tool_names:
                tool_use_counts[name] = tool_use_counts.get(name, 0) + 1

    if current_streak >= 2:
        reprompt_streaks.append(current_streak)

    duration = None
    if len(timestamps) >= 2:
        duration = (max(timestamps) - min(timestamps)).total_seconds()

    repeated_errors = {k: v for k, v in error_counts.items() if v >= 3}
    repeated_tool_errors = {k: v for k, v in tool_error_counts.items() if v >= 3}

    return SessionSignals(
        reprompt_streaks=reprompt_streaks,
        error_repeats=repeated_errors,
        duration_seconds=duration,
        models_used=sorted(models),
        turn_count=len(turns),
        tool_error_repeats=repeated_tool_errors,
        tools_used=tool_use_counts,
    )
