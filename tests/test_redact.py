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


# --- github tokens (classic + fine-grained) ---


def test_redacts_github_classic_pat():
    result = redact("token: ghp_1234567890abcdefghijklmnopqrstuv")
    assert "ghp_1234567890abcdefghijklmnopqrstuv" not in result
    assert "[REDACTED]" in result


def test_redacts_github_oauth_token():
    result = redact("gho_1234567890abcdefghijklmnopqrstuv")
    assert result == "[REDACTED]"


def test_redacts_github_fine_grained_pat():
    result = redact("github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyzABCDEFG")
    assert "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyzABCDEFG" not in result
    assert "[REDACTED]" in result


# --- slack tokens ---


def test_redacts_slack_bot_token():
    # Deliberately fake shape (letters where real tokens have digit runs):
    # still matches redact.py's xox[a-zA-Z]- pattern, but not GitHub push
    # protection's Slack detector — a realistic fixture blocks every push.
    result = redact("slack token is xoxb-FAKEFIXTURE-notarealtoken")
    assert "xoxb-FAKEFIXTURE-notarealtoken" not in result
    assert "[REDACTED]" in result


# --- JWT ---


def test_redacts_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ_abc123XYZ"
    result = redact(f"authorization header: {jwt}")
    assert jwt not in result
    assert "[REDACTED]" in result


# --- PEM private key blocks ---


def test_redacts_pem_private_key_block():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIBogIBAAJBAKj34GkxFhD91aRnJPTBZL4kR8v9Y6VuS7z1u1e2u1f8u1e2u1f8\n"
        "u1e2u1f8u1e2u1f8u1e2u1f8u1e2u1f8=\n"
        "-----END RSA PRIVATE KEY-----"
    )
    result = redact(f"here is my key:\n{pem}\nthanks")
    assert "MIIBogIBAAJBAKj34GkxFhD91aRnJPTBZL4kR8v9Y6VuS7z1u1e2u1f8u1e2u1f8" not in result
    assert "-----BEGIN RSA PRIVATE KEY-----" not in result
    assert "[REDACTED]" in result
    assert "here is my key" in result
    assert "thanks" in result


def test_redacts_pem_ec_private_key_block():
    pem = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIB\n-----END EC PRIVATE KEY-----"
    result = redact(pem)
    assert result == "[REDACTED]"


# --- password env assignments ---


def test_redacts_password_env():
    result = redact("DB_PASSWORD=hunter2andmore")
    assert "hunter2andmore" not in result
    assert "[REDACTED]" in result


def test_redacts_passwd_env():
    result = redact("ADMIN_PASSWD=letmein123")
    assert "letmein123" not in result
    assert "[REDACTED]" in result


def test_redacts_pwd_env():
    result = redact("MY_PWD=s3cr3t")
    assert "s3cr3t" not in result
    assert "[REDACTED]" in result


# --- URL userinfo credentials ---


def test_redacts_url_userinfo_password_keeps_rest_of_url():
    result = redact("connect to postgres://dbuser:p4ssw0rd@localhost:5432/mydb")
    assert "p4ssw0rd" not in result
    assert result == "connect to postgres://dbuser:[REDACTED]@localhost:5432/mydb"


def test_redacts_url_userinfo_password_https():
    result = redact("https://myuser:supersecret@example.com/path")
    assert "supersecret" not in result
    assert "https://myuser:[REDACTED]@example.com/path" == result


# --- env_secret quoted values with spaces ---


def test_redacts_env_secret_double_quoted_with_spaces():
    result = redact('API_KEY="value with spaces here" trailing text')
    assert "value with spaces here" not in result
    assert "[REDACTED]" in result
    assert "trailing text" in result


def test_redacts_env_secret_single_quoted_with_spaces():
    result = redact("API_TOKEN='another secret value' trailing text")
    assert "another secret value" not in result
    assert "[REDACTED]" in result
    assert "trailing text" in result


def test_env_secret_unquoted_still_works():
    """Regression: the quoted-value alternation must not break the
    existing bare \\S+ case."""
    result = redact("STRIPE_SECRET_KEY=sk_live_abcdef123456 trailing")
    assert "sk_live_abcdef123456" not in result
    assert "[REDACTED]" in result
    assert "trailing" in result
