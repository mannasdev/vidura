from vidura.chunk import chunk_turns, CHUNK_TARGET_CHARS
from vidura.ingest import Turn


def _turn(text):
    return Turn(type="user", timestamp=None, text=text, tool_use=False, model=None)


def test_single_small_turn_produces_one_chunk():
    turns = [_turn("short message")]
    chunks = chunk_turns(turns)
    assert len(chunks) == 1
    assert "short message" in chunks[0].text
    assert chunks[0].turn_count == 1


def test_turns_exceeding_target_split_into_two_chunks():
    big_text_1 = "a" * (CHUNK_TARGET_CHARS - 100)
    big_text_2 = "b" * 500
    turns = [_turn(big_text_1), _turn(big_text_2)]
    chunks = chunk_turns(turns)
    assert len(chunks) == 2
    assert "a" * 10 in chunks[0].text
    assert "b" * 10 in chunks[1].text


def test_empty_turn_text_skipped():
    turns = [_turn(""), _turn("real content")]
    chunks = chunk_turns(turns)
    assert len(chunks) == 1
    assert "real content" in chunks[0].text


def test_empty_turn_list_produces_no_chunks():
    assert chunk_turns([]) == []


def test_char_count_matches_chunk_text_for_single_turn():
    turns = [_turn("hello")]
    chunks = chunk_turns(turns)
    # a single-turn chunk's text is exactly that turn's formatted text,
    # so char_count (accumulated during the loop) must equal its length
    assert chunks[0].char_count == len(chunks[0].text)


def test_tool_result_turn_rendered_with_honest_label():
    from vidura.ingest import Turn
    turns = [Turn(type="user", timestamp=None, text="ls output", tool_use=False, model=None, is_tool_result=True)]
    chunks = chunk_turns(turns)
    assert chunks[0].text.startswith("[tool_result]")
    assert "[user]" not in chunks[0].text


def test_long_tool_result_truncated_in_chunk():
    from vidura.chunk import TOOL_RESULT_MAX_CHARS
    from vidura.ingest import Turn
    turns = [Turn(type="user", timestamp=None, text="x" * 5000, tool_use=False, model=None, is_tool_result=True)]
    chunks = chunk_turns(turns)
    assert "…[tool output truncated]" in chunks[0].text
    assert len(chunks[0].text) < 5000
