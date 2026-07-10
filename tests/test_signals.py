from vidura.ingest import Turn
from vidura.signals import extract_signals


def _turn(type_, text="", tool_use=False, timestamp=None, model=None):
    return Turn(type=type_, timestamp=timestamp, text=text, tool_use=tool_use, model=model)


def test_reprompt_streak_of_three_detected():
    turns = [
        _turn("user", "do the thing"),
        _turn("assistant", "here's a plan", tool_use=False),
        _turn("user", "no not like that"),
        _turn("assistant", "ok here's another plan", tool_use=False),
        _turn("user", "still wrong"),
        _turn("assistant", "using a tool now", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == [3]


def test_no_streak_when_tool_use_every_turn():
    turns = [
        _turn("user", "do the thing"),
        _turn("assistant", "doing it", tool_use=True),
        _turn("user", "do another thing"),
        _turn("assistant", "doing it", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == []


def test_trailing_streak_at_end_of_session_counted():
    turns = [
        _turn("user", "one"),
        _turn("user", "two"),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == [2]


def test_streak_of_one_not_counted():
    turns = [
        _turn("user", "one"),
        _turn("assistant", "ok", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == []


def test_repeated_error_marker_counted_at_three_plus():
    turns = [
        _turn("assistant", "Error: connection refused on port 5432"),
        _turn("assistant", "Error: connection refused on port 5432"),
        _turn("assistant", "Error: connection refused on port 5432"),
    ]
    signals = extract_signals(turns)
    assert len(signals.error_repeats) == 1
    assert list(signals.error_repeats.values())[0] == 3


def test_error_seen_twice_not_reported():
    turns = [
        _turn("assistant", "Error: timeout"),
        _turn("assistant", "Error: timeout"),
    ]
    signals = extract_signals(turns)
    assert signals.error_repeats == {}


def test_duration_computed_from_timestamps():
    turns = [
        _turn("user", "start", timestamp="2026-07-01T10:00:00.000Z"),
        _turn("assistant", "end", timestamp="2026-07-01T10:30:00.000Z", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.duration_seconds == 1800.0


def test_duration_none_with_fewer_than_two_timestamps():
    turns = [_turn("user", "hi", timestamp="2026-07-01T10:00:00.000Z")]
    signals = extract_signals(turns)
    assert signals.duration_seconds is None


def test_models_used_deduplicated_and_sorted():
    turns = [
        _turn("assistant", "a", model="claude-sonnet-5", tool_use=True),
        _turn("assistant", "b", model="claude-opus-4-8", tool_use=True),
        _turn("assistant", "c", model="claude-sonnet-5", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.models_used == ["claude-opus-4-8", "claude-sonnet-5"]


def test_turn_count():
    turns = [_turn("user", "a"), _turn("assistant", "b", tool_use=True)]
    signals = extract_signals(turns)
    assert signals.turn_count == 2
