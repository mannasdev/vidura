"""The reflection judgment core.

Prompt skeleton matches the original spec's §4.5 draft. call_ollama
enforces the 60s default timeout (design doc Eng Review Finding 2) via
urllib's built-in timeout — a TimeoutError or URLError there becomes a
ReflectorError, which the CLI (Task 9) catches and degrades to silence,
per design doc Premise #4.
"""

import json
import urllib.error
import urllib.request
from typing import Any

from vidura.contract import CONTRACT_VERSION, ReflectRequest, ReflectResponse, Suggestion

OLLAMA_DEFAULT_URL = "http://localhost:11434/api/generate"
OLLAMA_DEFAULT_MODEL = "qwen2.5:14b"

SYSTEM_PROMPT = """You are Vidura, a frank counselor. You read a developer's recent AI
coding sessions and identify at most 3 friction patterns where a known
remedy would materially help. You never flatter. You cite evidence.
If nothing clears the bar, output an empty list — silence is correct.

Rules: never suggest anything with a dismissed ledger entry; prefer
fix-index remedies over novel ones; every suggestion must quote
evidence; confidence is your honest probability the user adopts the
remedy AND benefits.

Output ONLY a JSON array of suggestion objects, no other text. Schema:
[{"fix_id": "<id from fix_index, or null if novel>", "confidence": <0-1 float>,
  "evidence": ["<quoted chunk excerpt>"], "blunt_summary": "<one sentence>",
  "novel": <true|false>}]
"""


class ReflectorError(Exception):
    pass


def build_prompt(request: ReflectRequest) -> str:
    fix_index_text = json.dumps(request.fix_index, indent=2)
    ledger_text = json.dumps(request.ledger, indent=2)
    signals_text = json.dumps(request.signals, indent=2)
    chunks_text = "\n\n---\n\n".join(request.chunks)
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"<signals>\n{signals_text}\n</signals>\n\n"
        f"<recent_sessions>\n{chunks_text}\n</recent_sessions>\n\n"
        f"<fix_index>\n{fix_index_text}\n</fix_index>\n\n"
        f"<ledger>\n{ledger_text}\n</ledger>\n"
    )


def call_ollama(
    prompt: str,
    model: str = OLLAMA_DEFAULT_MODEL,
    url: str = OLLAMA_DEFAULT_URL,
    timeout_seconds: int = 60,
) -> str:
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ReflectorError(f"ollama unreachable or timed out: {exc}") from exc
    response_text = payload.get("response")
    if not response_text:
        raise ReflectorError("ollama returned no response text")
    return response_text


def parse_suggestions(
    raw_response: str, confidence_floor_by_fix: dict[str, float]
) -> list[Suggestion]:
    try:
        parsed: Any = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ReflectorError(f"reflector output was not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ReflectorError("reflector output was not a JSON array")

    suggestions: list[Suggestion] = []
    for item in parsed:
        fix_id = item.get("fix_id")
        confidence = float(item.get("confidence", 0.0))
        floor = confidence_floor_by_fix.get(fix_id, 0.7) if fix_id else 0.8
        if confidence < floor:
            continue
        suggestions.append(
            Suggestion(
                fix_id=fix_id or "novel",
                confidence=confidence,
                evidence=item.get("evidence", []),
                blunt_summary=item.get("blunt_summary", ""),
                novel=fix_id is None,
            )
        )
    return suggestions


def reflect(
    request: ReflectRequest,
    model: str = OLLAMA_DEFAULT_MODEL,
    timeout_seconds: int = 60,
) -> ReflectResponse:
    prompt = build_prompt(request)
    raw_response = call_ollama(prompt, model=model, timeout_seconds=timeout_seconds)
    confidence_floor_by_fix = {
        f["id"]: f["confidence_floor"] for f in request.fix_index
    }
    suggestions = parse_suggestions(raw_response, confidence_floor_by_fix)
    return ReflectResponse(contract_version=CONTRACT_VERSION, suggestions=suggestions)
