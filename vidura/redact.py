# vidura/redact.py
"""Secret redaction — design doc Premise #6.

Runs before any chunk enters a reflector payload or is written to disk
— the two egress paths (claude -p reflection, supermemory push). No
exemptions by default.

Pattern ordering matters in one place: PEM blocks run FIRST (before
anything else) since a private key body is dense with characters (long
base64-ish runs, `=` padding) that could otherwise get partially
chewed by a narrower pattern running first and leaving a mangled
remainder; DOTALL lets `.` cross the embedded newlines inside the key
body. env_secret and password_env run LAST, after the more specific
token-shaped patterns (aws_key, llm_key_sk*, github_token, slack_token,
jwt) — e.g. `OPENAI_KEY=sk-...` gets its value redacted by llm_key_sk
first; the (?!\[REDACTED\]) guard on env_secret then stops it from
re-swallowing that placeholder together with the `OPENAI_KEY=` prefix.
"""

import re

REDACTED_PLACEHOLDER = "[REDACTED]"

REDACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # PEM key/cert blocks first — DOTALL so `.` spans the embedded
    # newlines of the key body; -----BEGIN ... PRIVATE KEY----- through
    # the matching -----END ... PRIVATE KEY----- footer, non-greedy so
    # multiple PEM blocks in one text redact independently.
    (
        "pem_private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-_.]+")),
    ("llm_key_sk_ant", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
    ("llm_key_sk", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    # GitHub personal access tokens (classic ghp_/gho_/ghu_/ghs_/ghr_
    # and fine-grained github_pat_), all a fixed prefix + a long
    # token-char run.
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    ),
    # Slack tokens: xoxb-, xoxp-, xoxa-, xoxs-, etc. — a single letter
    # after "xox" selects the token class, followed by dash-separated
    # segments.
    ("slack_token", re.compile(r"\bxox[a-zA-Z]-[A-Za-z0-9-]+")),
    # JWTs: three base64url segments (header.payload.signature); anchor
    # on the header/payload both starting with the base64url encoding
    # of `{"` (eyJ) — true of every standard JWT header and virtually
    # every JSON-object claims payload.
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    ),
    # URL userinfo credentials (scheme://user:pass@host) — redact only
    # the password, keeping scheme://user@host visible since the
    # username alone isn't the secret and the surrounding URL is often
    # useful context for the reflector.
    (
        "url_userinfo_password",
        re.compile(r"(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://[^\s:/@]+:)[^\s@]+(?=@)"),
    ),
    # PASSWORD/PASSWD/PWD env-style assignments — kept separate from
    # env_secret below since _KEY/_TOKEN/_SECRET don't cover this
    # naming family, and password leaks are exactly as real.
    (
        "password_env",
        re.compile(
            r"\b[A-Za-z][A-Za-z0-9_]*(?:PASSWORD|PASSWD|PWD)\s*=\s*(?!\[REDACTED\])(?:\"[^\"]*\"|'[^']*'|\S+)",
            re.IGNORECASE,
        ),
    ),
    # Case-insensitive: `my_api_key=...` and `Stripe_Secret=...` are just
    # as real a leak as `STRIPE_SECRET=...` and must be caught too.
    # Quoted values ("..."/'...') are matched whole (including embedded
    # spaces) before falling back to \S+ for the unquoted case — a bare
    # \S+ alone stops at the first space and leaks the rest of a quoted
    # multi-word secret.
    (
        "env_secret",
        re.compile(
            r"\b[A-Za-z][A-Za-z0-9_]*(?:_KEY|_TOKEN|_SECRET)\s*=\s*(?!\[REDACTED\])(?:\"[^\"]*\"|'[^']*'|\S+)",
            re.IGNORECASE,
        ),
    ),
]


def redact(text: str) -> str:
    if not text:
        return text
    redacted = text
    for name, pattern in REDACTION_PATTERNS:
        if name == "url_userinfo_password":
            redacted = pattern.sub(lambda m: m.group("prefix") + REDACTED_PLACEHOLDER, redacted)
        else:
            redacted = pattern.sub(REDACTED_PLACEHOLDER, redacted)
    return redacted
