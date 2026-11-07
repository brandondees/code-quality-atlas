# SPDX-License-Identifier: MIT
import pytest

from atlas_reviewer.redact import TRUNCATION_MARKER, RedactedText, Redactor, redact

from .helpers import fake_token

PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIfake\n-----END RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    "secret,label",
    [
        (fake_token("ghs_"), "github-token"),
        (fake_token("ghp_"), "github-token"),
        (fake_token("github_pat_", 40), "github-pat"),
        (fake_token("sk-ant-", 30), "model-key"),
        ("AKIAIOSFODNN7EXAMPLE", "aws-key-id"),
        (fake_token("xoxb-", 20), "slack-token"),
        ("eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "jwt"),
        ("Bearer " + fake_token("", 24), "bearer"),
        (PRIVATE_KEY, "private-key"),
    ],
)
def test_known_secret_shapes_are_redacted(secret, label):
    result = redact(f"before {secret} after")
    assert secret not in result.text
    assert f"[REDACTED:{label}]" in result.text
    assert result.redaction_count >= 1


def test_assignment_keeps_the_key_and_drops_the_value():
    result = redact('password = "correct-horse-battery"')
    assert result.text == 'password = "[REDACTED:assignment]"'


def test_controller_credentials_are_scrubbed_by_exact_value():
    redactor = Redactor(("org/123/plainsecretvalue", "short"))
    result = redactor("token org/123/plainsecretvalue and short")
    assert "plainsecretvalue" not in result.text
    assert "short" in result.text
    assert result.redaction_count == 1


def test_clean_text_is_untouched_and_truncation_is_marked():
    assert redact("nothing to see").text == "nothing to see"
    long = redact("x" * 50, max_chars=10)
    assert long.text == "x" * 10 + TRUNCATION_MARKER


def test_truncation_is_recorded_with_the_original_length():
    cut = redact("x" * 50, max_chars=10)
    assert cut.truncated_from == 50
    assert redact("x" * 10, max_chars=10).truncated_from is None
    assert redact("x" * 50).truncated_from is None


def test_redacted_text_cannot_be_constructed_directly():
    with pytest.raises(TypeError):
        RedactedText("raw secret", 0)
