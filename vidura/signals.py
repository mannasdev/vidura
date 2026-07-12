"""Cheap structural friction signals — no model call needed.

Mirrors the original spec's Ingestor signal list: re-prompt streaks,
error loops (same error string 3+ times), session duration, and models
used.

Error loops are detected in both assistant text and tool-result turns:
tracebacks and build failures arrive as tool_result records, so scanning
only assistant text missed most real error loops. Assistant-text errors
feed error_repeats (which gates sweep inclusion); tool-result errors feed
the separate, judge-visibility-only tool_error_repeats (see its docstring
for why the two must never merge). Both use ERROR_MARKERS plus the
tool_result is_error flag, and error keys are normalized (digits, hex,
absolute paths, whitespace) so the same logical error dedupes across
line numbers, addresses, and file locations.

Re-prompt streaks track *friction*, not conversation length. A text-only
assistant reply arms a gate: the streak continues past it only if the
next human turn reads as a correction/retry (CORRECTION_MARKERS).
Otherwise a pure Q&A session would accumulate one giant streak and
monopolize sweep batches.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from vidura.ingest import Turn

ERROR_MARKERS = ("Error:", "Traceback", "Exception:", "failed:")

# Correction/retry markers matched case-insensitively as substrings of the
# human turn that follows a text-only assistant reply. Deliberately narrow:
# a follow-up question without any of these ends the streak.
CORRECTION_MARKERS = (
    "no,",
    "no.",
    "not what",
    "that's not",
    "i meant",
    "i said",
    "again",
    "still doesn't",
    "still not",
    "doesn't work",
    "didn't work",
    "wrong",
    "instead",
    "undo",
    "revert",
    "actually",
)

# Key normalization order matters: paths first (their segments may contain
# digits/hex), 0x-hex before bare digit runs (so the "0x" prefix doesn't
# survive alone). Bare hex requires at least one digit so hex-alphabet
# English words ("facade", "decade") stay readable.
_PATH_RE = re.compile(r"(?<![\w/])/(?:[\w.\-]+/)+[\w.\-]+")
_HEX_0X_RE = re.compile(r"0x[0-9a-fA-F]+")
_BARE_HEX_RE = re.compile(r"\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{6,}\b")
_DIGITS_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


@dataclass
class SessionSignals:
    reprompt_streaks: list[int]
    error_repeats: dict[str, int]
    duration_seconds: float | None
    models_used: list[str]
    turn_count: int
    # Errors seen inside tool_result turns (e.g. a traceback in command
    # output) — counted the same way as error_repeats (ERROR_MARKERS plus
    # the is_error flag, normalized keys, 3+ threshold) but kept in a
    # SEPARATE field on purpose.
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


def _normalize_key(key: str) -> str:
    key = _PATH_RE.sub("<path>", key)
    key = _HEX_0X_RE.sub("#", key)
    key = _BARE_HEX_RE.sub("#", key)
    key = _DIGITS_RE.sub("#", key)
    return _WS_RE.sub(" ", key).strip()


def _error_key(text: str, marker: str) -> str:
    idx = text.find(marker)
    return _normalize_key(text[idx: idx + 80])


def _first_line_key(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    return _normalize_key(first_line[:80])


def _turn_error_keys(turn: Turn) -> set[str]:
    # Set-valued so one turn never double-counts a key — the marker-derived
    # key and the is_error first-line key often normalize identically.
    keys: set[str] = set()
    for marker in ERROR_MARKERS:
        if marker in turn.text:
            keys.add(_error_key(turn.text, marker))
    if turn.is_error and turn.text.strip():
        keys.add(_first_line_key(turn.text))
    return keys


def _is_correction(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CORRECTION_MARKERS)


def extract_signals(turns: list[Turn]) -> SessionSignals:
    reprompt_streaks: list[int] = []
    current_streak = 0
    # Armed by a text-only assistant reply; the next human turn must carry
    # correction semantics or the streak flushes before it.
    conversation_gate = False
    error_counts: dict[str, int] = {}
    tool_error_counts: dict[str, int] = {}
    tool_use_counts: dict[str, int] = {}
    models: set[str] = set()
    timestamps: list[datetime] = []

    def flush_streak() -> None:
        nonlocal current_streak
        if current_streak >= 2:
            reprompt_streaks.append(current_streak)
        current_streak = 0

    for turn in turns:
        ts = _parse_ts(turn.timestamp)
        if ts is not None:
            timestamps.append(ts)
        if turn.model:
            models.add(turn.model)

        if turn.type == "user":
            if turn.is_tool_result:
                # Tool results arrive as user-type records but are not human
                # prompts — counting them inflated streaks with machine noise
                # (observed in M0). They are transparent to both the streak
                # and the conversation gate, but they DO carry errors —
                # counted into the SEPARATE tool_error_counts (see
                # SessionSignals.tool_error_repeats for why they never
                # merge into error_counts).
                for key in _turn_error_keys(turn):
                    tool_error_counts[key] = tool_error_counts.get(key, 0) + 1
            else:
                if conversation_gate and not _is_correction(turn.text):
                    flush_streak()
                conversation_gate = False
                current_streak += 1
        elif turn.type == "assistant":
            if turn.tool_use:
                flush_streak()
                conversation_gate = False
            elif turn.text.strip():
                conversation_gate = True
            for key in _turn_error_keys(turn):
                error_counts[key] = error_counts.get(key, 0) + 1
            for name in turn.tool_names:
                tool_use_counts[name] = tool_use_counts.get(name, 0) + 1

    flush_streak()

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
