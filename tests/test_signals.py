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


def _tool_result(text, is_error=False, timestamp=None):
    return Turn(
        type="user",
        timestamp=timestamp,
        text=text,
        tool_use=False,
        model=None,
        is_tool_result=True,
        is_error=is_error,
    )


def test_reprompt_streak_of_three_detected():
    # Each user turn after an assistant text reply carries a correction
    # marker, so the whole exchange is one friction streak.
    turns = [
        _turn("user", "do the thing"),
        _turn("assistant", "here's a plan", tool_use=False),
        _turn("user", "no, not like that"),
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


# --- error markers and is_error in tool results (FIX 3) ---


def test_error_marker_in_tool_result_counted():
    tb = "Traceback (most recent call last):\n  File \"app.py\"\nValueError: bad input"
    turns = [_tool_result(tb), _tool_result(tb), _tool_result(tb)]
    signals = extract_signals(turns)
    # tb trips both "Traceback" and "Error:" markers — each key repeats 3x.
    # Tool-result errors land in the separate judge-visibility signal.
    assert signals.tool_error_repeats
    assert all(count == 3 for count in signals.tool_error_repeats.values())
    assert signals.error_repeats == {}


def test_is_error_flag_counted_without_marker():
    text = "npm exited with nonzero status\nsee log above"
    turns = [
        _tool_result(text, is_error=True),
        _tool_result(text, is_error=True),
        _tool_result(text, is_error=True),
    ]
    signals = extract_signals(turns)
    assert len(signals.tool_error_repeats) == 1
    assert list(signals.tool_error_repeats.values())[0] == 3


def test_is_error_with_empty_text_not_counted():
    turns = [
        _tool_result("   ", is_error=True),
        _tool_result("", is_error=True),
        _tool_result("\n", is_error=True),
    ]
    signals = extract_signals(turns)
    assert signals.tool_error_repeats == {}
    assert signals.error_repeats == {}


def test_marker_and_is_error_same_key_not_double_counted():
    # Marker sits at the start of the first line, so the marker-derived key
    # and the is_error first-line key normalize identically; each turn must
    # contribute 1, not 2.
    text = "Error: connection refused on port 5432"
    turns = [
        _tool_result(text, is_error=True),
        _tool_result(text, is_error=True),
        _tool_result(text, is_error=True),
    ]
    signals = extract_signals(turns)
    assert list(signals.tool_error_repeats.values()) == [3]


def test_assistant_and_tool_result_error_keys_normalize_identically():
    # The same logical error must produce the SAME key in both dicts —
    # sources stay separate (error_repeats gates, tool_error_repeats
    # doesn't), but the vocabulary is shared.
    text = "Error: connection refused on port 5432"
    turns = [
        _turn("assistant", text, tool_use=True),
        _turn("assistant", text, tool_use=True),
        _turn("assistant", text, tool_use=True),
        _tool_result(text),
        _tool_result(text),
        _tool_result(text),
    ]
    signals = extract_signals(turns)
    assert list(signals.error_repeats.values()) == [3]
    assert list(signals.tool_error_repeats.values()) == [3]
    assert next(iter(signals.error_repeats)) == next(iter(signals.tool_error_repeats))


# --- error key normalization (FIX 4a) ---


def test_error_keys_dedupe_across_line_numbers():
    turns = [
        _turn("assistant", "Error: parse failure at line 12", tool_use=True),
        _turn("assistant", "Error: parse failure at line 47", tool_use=True),
        _turn("assistant", "Error: parse failure at line 213", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert len(signals.error_repeats) == 1
    key = next(iter(signals.error_repeats))
    assert "#" in key
    assert "12" not in key


def test_error_keys_dedupe_across_paths_and_addresses():
    turns = [
        _tool_result("Error: cannot mmap /Users/a/proj/one.py at 0x7f3a9c1200"),
        _tool_result("Error: cannot mmap /home/b/other/two.py at 0xdeadbeef42"),
        _tool_result("Error: cannot mmap /tmp/build/three.py at 0x10a4f2000"),
    ]
    signals = extract_signals(turns)
    assert len(signals.tool_error_repeats) == 1
    key = next(iter(signals.tool_error_repeats))
    assert "<path>" in key
    assert "0x" not in key


def test_error_keys_collapse_whitespace_and_bare_hex():
    turns = [
        _tool_result("Error: object   a3f9c2e1b4 unreachable"),
        _tool_result("Error: object 9bd041cc7e  unreachable"),
        _tool_result("Error: object  55aa10ffee unreachable"),
    ]
    signals = extract_signals(turns)
    assert list(signals.tool_error_repeats.values()) == [3]


# --- streak semantics with conversational replies (FIX 4b) ---


def test_qa_session_produces_no_streaks():
    turns = [
        _turn("user", "how does asyncio work?"),
        _turn("assistant", "asyncio is an event loop..."),
        _turn("user", "and what about threads?"),
        _turn("assistant", "threads differ because..."),
        _turn("user", "which should I pick here?"),
        _turn("assistant", "for IO-bound work, asyncio."),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == []


def test_correction_chain_through_text_replies_accumulates():
    turns = [
        _turn("user", "write the migration"),
        _turn("assistant", "here is the migration plan"),
        _turn("user", "that's not what I asked for"),
        _turn("assistant", "understood, revised plan"),
        _turn("user", "it still doesn't handle nulls"),
        _turn("assistant", "third attempt at the plan"),
        _turn("user", "I meant the users table"),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == [4]


def test_non_correction_after_text_reply_starts_fresh_streak():
    turns = [
        _turn("user", "explain the config"),
        _turn("assistant", "the config does X"),
        _turn("user", "ok now build the parser"),
        _turn("user", "and add tests for it"),
    ]
    signals = extract_signals(turns)
    # First streak dies at 1 (unrecorded); the two back-to-back human turns
    # form their own streak.
    assert signals.reprompt_streaks == [2]


def test_tool_use_still_resets_streak():
    turns = [
        _turn("user", "run the build"),
        _turn("assistant", "running", tool_use=True),
        _turn("user", "now lint it"),
        _turn("assistant", "linting", tool_use=True),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == []


def test_tool_results_transparent_to_conversation_gate():
    turns = [
        _turn("user", "fix the bug"),
        _turn("assistant", "I believe the bug is in foo()"),
        _tool_result("some hook output"),
        _turn("user", "wrong function, look at bar()"),
    ]
    signals = extract_signals(turns)
    assert signals.reprompt_streaks == [2]
