"""vidura-reflect: the subprocess entrypoint (Approach C).

stdin: JSON ReflectRequest. stdout: JSON ReflectResponse.

Contract version mismatch and unparseable stdin both fail LOUDLY
(non-zero exit, stderr message) — these are caller-side bugs, not
judgment-unavailable cases, so they must NOT degrade to silence.

Every reflector failure (claude CLI missing, timeout, malformed model
output) degrades to silence per design doc Premise #4: empty
suggestions list, exit 0. This is a broad `except Exception`, not just
ReflectorError — subprocess/parsing exceptions can escape reflect()'s own
net and must still degrade rather than crash the caller.
"""

import json
import sys

from vidura.contract import (
    CONTRACT_VERSION,
    PAYLOAD_BUDGET_CHARS,
    ContractVersionMismatch,
    ReflectRequest,
    ReflectResponse,
    enforce_payload_budget,
    validate_contract_version,
)
from vidura.reflect import ReflectorError, reflect


def main(argv: list[str] | None = None) -> int:
    raw_input = sys.stdin.read()

    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        print(f"vidura-reflect: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print(f"vidura-reflect: expected a JSON object on stdin, got {type(payload).__name__}", file=sys.stderr)
        return 2

    try:
        validate_contract_version(payload)
    except ContractVersionMismatch as exc:
        print(f"vidura-reflect: {exc}", file=sys.stderr)
        return 2

    chunks = enforce_payload_budget(payload.get("chunks", []), budget_chars=PAYLOAD_BUDGET_CHARS)
    request = ReflectRequest(
        contract_version=payload["contract_version"],
        signals=payload.get("signals", {}),
        chunks=chunks,
        fix_index=payload.get("fix_index", []),
        ledger=payload.get("ledger", []),
        similar_past_friction=payload.get("similar_past_friction", []),
    )

    try:
        response = reflect(request)
    except ReflectorError as exc:
        print(f"vidura-reflect: degrading to silence: {exc}", file=sys.stderr)
        response = ReflectResponse(contract_version=CONTRACT_VERSION, suggestions=[])
    except Exception as exc:
        # Design doc Premise #4: judgment-unavailable must never crash the
        # tool. ReflectorError covers the reflector's own known failure
        # modes, but exceptions can still escape it (e.g. a
        # KeyError from a malformed fix_index entry in reflect()) — any of
        # those must degrade to silence too, not propagate.
        print(f"vidura-reflect: degrading to silence (unexpected error): {exc}", file=sys.stderr)
        response = ReflectResponse(contract_version=CONTRACT_VERSION, suggestions=[])

    print(json.dumps(response.to_json_dict()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
