"""Claude Code session JSONL parser.

Schema notes (verified against real ~/.claude/projects/**/*.jsonl files):
each line is a JSON object with a "type" field. We only care about
"user" and "assistant" types; other types (mode, permission-mode,
ai-title, file-history-snapshot, attachment, queue-operation, system,
last-prompt) are structural/metadata records, not conversational turns.

user/assistant records have a "message" object with "content" that is
either a plain string or a list of content blocks ({"type": "text"},
{"type": "tool_use"}, {"type": "tool_result"}). Assistant records also
carry "model" on the message object.

Malformed lines are skipped and logged, not fatal — design doc
Eng Review Finding 5: a single bad line (e.g. a mid-flush truncation on
an actively-appended file) shouldn't blind friction detection for the
rest of an otherwise-readable session.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Turn:
    type: str
    timestamp: str | None
    text: str
    tool_use: bool
    model: str | None


def _extract_text_and_tool_use(message: dict[str, Any]) -> tuple[str, bool]:
    content = message.get("content")
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False

    text_parts: list[str] = []
    tool_use = False
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_use = True
        elif block_type == "tool_result":
            result_content = block.get("content")
            if isinstance(result_content, str):
                text_parts.append(result_content)
    return "\n".join(text_parts), tool_use


def parse_session(path: Path) -> Iterator[Turn]:
    with path.open("r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                print(f"vidura: skipping malformed line {line_num} in {path}")
                continue

            record_type = record.get("type")
            if record_type not in ("user", "assistant"):
                continue

            message = record.get("message")
            if not isinstance(message, dict):
                continue

            text, tool_use = _extract_text_and_tool_use(message)
            yield Turn(
                type=record_type,
                timestamp=record.get("timestamp"),
                text=text,
                tool_use=tool_use,
                model=message.get("model"),
            )
