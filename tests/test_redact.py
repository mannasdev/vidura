# tests/test_redact.py
from vidura.redact import redact


def test_redacts_aws_key():
    assert redact("key is AKIAABCDEFGHIJKLMNOP") == "key is [REDACTED]"


def test_redacts_bearer_token():
    assert redact("Authorization: Bearer abc123.XYZ-_token") == "Authorization: [REDACTED]"


def test_redacts_env_secret():
    assert redact("STRIPE_SECRET_KEY=sk_live_abcdef123456") == "[REDACTED]"


def test_redacts_llm_key_sk():
    assert redact("export OPENAI_KEY=sk-abcdefghijklmnopqrstuvwx") == "export OPENAI_KEY=[REDACTED]"


def test_redacts_llm_key_sk_ant():
    assert redact("token: sk-ant-api03-abcdefghijklmnopqrstuvwxyz") == "token: [REDACTED]"


def test_passthrough_for_non_matching_text():
    text = "the user asked to refactor the auth module"
    assert redact(text) == text


def test_empty_string_passthrough():
    assert redact("") == ""


def test_redacts_lowercase_env_secret():
    result = redact("my_api_key=secret123")
    assert "secret123" not in result
    assert "[REDACTED]" in result


def test_redacts_mixed_case_env_secret():
    result = redact("Stripe_Secret=abc")
    assert "abc" not in result
    assert "[REDACTED]" in result


def test_redacts_multiple_secrets_in_one_string():
    text = "key is AKIAABCDEFGHIJKLMNOP and Authorization: Bearer abc123.XYZ-_token"
    result = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in result
    assert "abc123.XYZ-_token" not in result
    assert result.count("[REDACTED]") == 2
