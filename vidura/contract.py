"""The vidura-reflect JSON stdin/stdout contract.

Design doc Next Steps #3 and Eng Review Findings 1, 2, 4, 7:
- contract_version: rejected loudly on mismatch, never silently.
- chunk text is inlined (not passed by SQLite reference) — the
  reflector stays a pure function, JSON in, JSON out.
- payload budget: enforced before the payload is built, so a long
  session can't silently overflow the reflector model's context window.
- timeout: enforced by the caller (Task 8's Ollama call), not here.

PAYLOAD_BUDGET_CHARS is the one operative default, shared by both
callers (vidura/cli.py and vidura/report.py) so they can't silently
re-cut an already-budgeted payload to a smaller size. It reflects the
reflector's 16384-token context window (reflect.OLLAMA_NUM_CTX), which
comfortably fits ~48k chars of chunks plus prompt scaffolding.
DEFAULT_PAYLOAD_BUDGET_CHARS is kept as an alias for callers/tests that
still reference the old name.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

CONTRACT_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 60
PAYLOAD_BUDGET_CHARS = 48000
DEFAULT_PAYLOAD_BUDGET_CHARS = PAYLOAD_BUDGET_CHARS  # alias — old name


class ContractVersionMismatch(Exception):
    pass


@dataclass
class ReflectRequest:
    contract_version: int
    signals: dict[str, Any]
    chunks: list[str]
    fix_index: list[dict[str, Any]]
    ledger: list[dict[str, Any]]

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Suggestion:
    fix_id: str
    confidence: float
    evidence: list[str]
    blunt_summary: str
    novel: bool = False


@dataclass
class ReflectResponse:
    contract_version: int
    suggestions: list[Suggestion] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "suggestions": [asdict(s) for s in self.suggestions],
        }


def validate_contract_version(payload: dict[str, Any]) -> None:
    version = payload.get("contract_version")
    if version != CONTRACT_VERSION:
        raise ContractVersionMismatch(
            f"expected contract_version={CONTRACT_VERSION}, got {version!r}"
        )


def enforce_payload_budget(
    chunks: list[str], budget_chars: int = PAYLOAD_BUDGET_CHARS
) -> list[str]:
    """Keep the most recent chunks that fit budget_chars, dropping the
    oldest first. Always keeps at least one chunk even if it alone
    exceeds the budget — a single oversized chunk should still reach
    the reflector rather than producing an empty payload."""
    kept: list[str] = []
    total = 0
    for chunk in reversed(chunks):
        if total + len(chunk) > budget_chars and kept:
            break
        kept.append(chunk)
        total += len(chunk)
    kept.reverse()
    return kept
