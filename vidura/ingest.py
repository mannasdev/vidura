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
import sys
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
    # Claude Code delivers tool RESULTS as user-type records. A tool-result
    # turn is not a human prompt: it must not count as a re-prompt in the
    # streak signal and must not render as "[user]" in chunks (observed
    # live in M0: tool-output spam dominated the friction-density ranking
    # while carrying zero human friction).
    is_tool_result: bool = False


def _extract_text_and_tool_use(message: dict[str, Any]) -> tuple[str, bool, bool]:
    content = message.get("content")
    if isinstance(content, str):
        return content, False, False
    if not isinstance(content, list):
        return "", False, False

    text_parts: list[str] = []
    tool_use = False
    has_tool_result = False
    has_human_text = False
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            if block.get("text", "").strip():
                has_human_text = True
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_use = True
        elif block_type == "tool_result":
            has_tool_result = True
            result_content = block.get("content")
            if isinstance(result_content, str):
                text_parts.append(result_content)
    is_tool_result = has_tool_result and not has_human_text
    return "\n".join(text_parts), tool_use, is_tool_result


def parse_session(path: Path) -> Iterator[Turn]:
    with path.open("r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                print(f"vidura: skipping malformed line {line_num} in {path}", file=sys.stderr)
                continue

            record_type = record.get("type")
            if record_type not in ("user", "assistant"):
                continue

            message = record.get("message")
            if not isinstance(message, dict):
                continue

            text, tool_use, is_tool_result = _extract_text_and_tool_use(message)
            yield Turn(
                type=record_type,
                timestamp=record.get("timestamp"),
                text=text,
                tool_use=tool_use,
                model=message.get("model"),
                is_tool_result=is_tool_result,
            )
