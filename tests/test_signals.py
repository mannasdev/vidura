from vidura.ingest import Turn
from vidura.signals import extract_signals


def _turn(type_, text="", tool_use=False, timestamp=None, model=None, tool_names=None):
    return Turn(
        type=type_,
        timestamp=timestamp,
        text=text,
        tool_use=tool_use,
        model=model,
        tool_names=tool_names or [],
    )


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


def test_tool_result_turns_do_not_count_in_streaks():
    turns = [
        _turn("user", "do the thing"),
        Turn(type="user", timestamp=None, text="tool output", tool_use=False, model=None, is_tool_result=True),
        Turn(type="user", timestamp=None, text="more tool output", tool_use=False, model=None, is_tool_result=True),
        _turn("assistant", "ok", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == []


def _tool_result_turn(text):
    return Turn(type="user", timestamp=None, text=text, tool_use=False, model=None, is_tool_result=True)


def test_tool_result_error_repeated_three_plus_counted_separately():
    turns = [
        _tool_result_turn("Error: connection refused on port 5432"),
        _tool_result_turn("Error: connection refused on port 5432"),
        _tool_result_turn("Error: connection refused on port 5432"),
    ]
    signals = extract_signals(turns)
    assert len(signals.tool_error_repeats) == 1
    assert list(signals.tool_error_repeats.values())[0] == 3
    # must NOT bleed into the assistant-turn error_repeats signal
    assert signals.error_repeats == {}


def test_tool_result_errors_do_not_gate_or_pollute_error_repeats():
    """tool_error_repeats is a separate, judge-visibility-only signal —
    it must never merge into error_repeats (which gates session
    inclusion in sweep.py/report.py and feeds character.py's robot
    threshold)."""
    turns = [
        _tool_result_turn("Error: from tool a"),
        _tool_result_turn("Error: from tool a"),
        _tool_result_turn("Error: from tool a"),
        _turn("assistant", "Error: from assistant"),
        _turn("assistant", "Error: from assistant"),
        _turn("assistant", "Error: from assistant"),
    ]
    signals = extract_signals(turns)
    assert len(signals.error_repeats) == 1
    assert len(signals.tool_error_repeats) == 1
    # values track their own source only
    assert list(signals.error_repeats.values())[0] == 3
    assert list(signals.tool_error_repeats.values())[0] == 3


def test_tool_result_error_seen_twice_not_reported():
    turns = [
        _tool_result_turn("Error: timeout"),
        _tool_result_turn("Error: timeout"),
    ]
    signals = extract_signals(turns)
    assert signals.tool_error_repeats == {}


def test_tools_used_counts_calls_across_assistant_turns():
    turns = [
        _turn("assistant", "reading", tool_use=True, tool_names=["Read"]),
        _turn("assistant", "reading again", tool_use=True, tool_names=["Read"]),
        _turn("assistant", "clicking", tool_use=True, tool_names=["mcp__playwright__click"]),
    ]
    signals = extract_signals(turns)
    assert signals.tools_used == {"Read": 2, "mcp__playwright__click": 1}


def test_tools_used_multiple_tool_calls_in_one_turn_all_counted():
    turns = [
        _turn("assistant", "multi-tool turn", tool_use=True, tool_names=["Read", "Bash", "Read"]),
    ]
    signals = extract_signals(turns)
    assert signals.tools_used == {"Read": 2, "Bash": 1}


def test_tools_used_empty_when_no_tool_calls():
    turns = [
        _turn("user", "hi"),
        _turn("assistant", "hello back"),
    ]
    signals = extract_signals(turns)
    assert signals.tools_used == {}


def test_tools_used_ignores_user_turn_tool_names():
    """tool_names is only ever populated on assistant turns by ingest.py,
    but extract_signals should not count it from a user-type Turn even if
    one were (defensively) constructed with tool_names set."""
    turns = [
        _turn("user", "hi", tool_names=["should-not-count"]),
        _turn("assistant", "ok", tool_use=True, tool_names=["Read"]),
    ]
    signals = extract_signals(turns)
    assert signals.tools_used == {"Read": 1}
