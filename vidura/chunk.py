"""Turn-group chunking — design doc's "~1-2k tokens" retrieval unit.

CHUNK_TARGET_CHARS approximates 1.5k tokens at ~4 chars/token. This is
a rougher granularity decision than the design doc's Open Question #3
(turn-groups vs. whole-session summaries) fully resolves — turn-groups
is the choice made here, consistent with the original spec's wording.
"""

from dataclasses import dataclass

from vidura.ingest import Turn

CHUNK_TARGET_CHARS = 6000
TOOL_RESULT_MAX_CHARS = 400


@dataclass
class Chunk:
    text: str
    turn_count: int
    char_count: int


def chunk_turns(turns: list[Turn]) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_chars = 0
    buffer_turns = 0

    def flush() -> None:
        nonlocal buffer, buffer_chars, buffer_turns
        if buffer:
            chunks.append(Chunk(text="\n\n".join(buffer), turn_count=buffer_turns, char_count=buffer_chars))
        buffer = []
        buffer_chars = 0
        buffer_turns = 0

    for turn in turns:
        # Tool results are user-type records but not human speech — label
        # them honestly so "[user]" in a chunk always means a human prompt
        # (the report's friction-density ranking depends on this), and cap
        # their length: a single ls/build dump was eating whole chunks,
        # crowding out the dialogue the reflector judges.
        if turn.is_tool_result:
            text = turn.text
            if len(text) > TOOL_RESULT_MAX_CHARS:
                text = text[:TOOL_RESULT_MAX_CHARS] + " …[tool output truncated]"
            turn_text = f"[tool_result] {text}".strip()
        else:
            turn_text = f"[{turn.type}] {turn.text}".strip()
        if not turn.text:
            continue
        if buffer_chars + len(turn_text) > CHUNK_TARGET_CHARS and buffer:
            flush()
        buffer.append(turn_text)
        buffer_chars += len(turn_text)
        buffer_turns += 1

    flush()
    return chunks
