# vidura/redact.py
"""Secret redaction — design doc Premise #6.

Runs before any chunk enters a reflector payload or is written to disk.
No exemptions by default.
"""

import re

REDACTED_PLACEHOLDER = "[REDACTED]"

REDACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-_.]+")),
    ("llm_key_sk_ant", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
    ("llm_key_sk", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    # Runs after the llm_key patterns above so that, e.g., `OPENAI_KEY=sk-...`
    # gets its value redacted by llm_key_sk first; the (?!\[REDACTED\])
    # guard stops this pattern from then re-swallowing that placeholder
    # together with the `OPENAI_KEY=` prefix.
    ("env_secret", re.compile(r"\b[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET)\s*=\s*(?!\[REDACTED\])\S+")),
]


def redact(text: str) -> str:
    if not text:
        return text
    redacted = text
    for _name, pattern in REDACTION_PATTERNS:
        redacted = pattern.sub(REDACTED_PLACEHOLDER, redacted)
    return redacted
