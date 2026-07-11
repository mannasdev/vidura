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
from dataclasses import dataclass, field
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
    # The "name" field off each tool_use block on an assistant turn (e.g.
    # "Read", "Bash", or an MCP-style "mcp__playwright__click"). Substrate
    # for the tool-usage signal (signals.py's tools_used) — the raw
    # per-turn list, not yet aggregated; extraction happens once here so
    # both signals.py and any future direct consumer read the same shape.
    tool_names: list[str] = field(default_factory=list)
    # Claude Code sets "is_error": true on failed tool_result blocks. The
    # flag catches failures whose text carries no recognizable error marker
    # (e.g. a build tool that prints a summary and exits nonzero).
    is_error: bool = False


def _extract_text_and_tool_use(
    message: dict[str, Any],
) -> tuple[str, bool, bool, bool, list[str]]:
    content = message.get("content")
    if isinstance(content, str):
        return content, False, False, False, []
    if not isinstance(content, list):
        return "", False, False, False, []

    text_parts: list[str] = []
    tool_use = False
    has_tool_result = False
    has_human_text = False
    is_error = False
    tool_names: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            # `or ""`: a literal `"text": null` in the JSON must not crash
            # ingest — malformed lines degrade, never blind the whole session.
            block_text = block.get("text") or ""
            if block_text.strip():
                has_human_text = True
            text_parts.append(block_text)
        elif block_type == "tool_use":
            tool_use = True
            name = block.get("name")
            if isinstance(name, str) and name:
                tool_names.append(name)
        elif block_type == "tool_result":
            has_tool_result = True
            if block.get("is_error"):
                is_error = True
            result_content = block.get("content")
            if isinstance(result_content, str):
                text_parts.append(result_content)
            elif isinstance(result_content, list):
                # ~13% of real tool_result blocks carry content as a list of
                # blocks (mirroring assistant content) rather than a plain
                # string; only "text" blocks hold readable output — images
                # and malformed entries are skipped. Dropping this shape
                # made tracebacks surfacing this way invisible to both
                # chunking and signal extraction.
                inner = [
                    item.get("text") or ""
                    for item in result_content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if inner:
                    text_parts.append("\n".join(inner))
    is_tool_result = has_tool_result and not has_human_text
    return "\n".join(text_parts), tool_use, is_tool_result, is_error, tool_names


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

            text, tool_use, is_tool_result, is_error, tool_names = _extract_text_and_tool_use(message)
            yield Turn(
                type=record_type,
                timestamp=record.get("timestamp"),
                text=text,
                tool_use=tool_use,
                model=message.get("model"),
                is_tool_result=is_tool_result,
                tool_names=tool_names,
                is_error=is_error,
            )
