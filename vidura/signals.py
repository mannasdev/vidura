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
    models: set[str] = set()
    timestamps: list[datetime] = []

    for turn in turns:
        ts = _parse_ts(turn.timestamp)
        if ts is not None:
            timestamps.append(ts)
        if turn.model:
            models.add(turn.model)

        if turn.type == "user":
            current_streak += 1
        elif turn.type == "assistant":
            if turn.tool_use:
                if current_streak >= 2:
                    reprompt_streaks.append(current_streak)
                current_streak = 0
            for marker in ERROR_MARKERS:
                if marker in turn.text:
                    key = _error_key(turn.text, marker)
                    error_counts[key] = error_counts.get(key, 0) + 1

    if current_streak >= 2:
        reprompt_streaks.append(current_streak)

    duration = None
    if len(timestamps) >= 2:
        duration = (max(timestamps) - min(timestamps)).total_seconds()

    repeated_errors = {k: v for k, v in error_counts.items() if v >= 3}

    return SessionSignals(
        reprompt_streaks=reprompt_streaks,
        error_repeats=repeated_errors,
        duration_seconds=duration,
        models_used=sorted(models),
        turn_count=len(turns),
    )
