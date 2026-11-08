# SPDX-License-Identifier: MIT
import pytest

from atlas_reviewer.redact import (
    TRUNCATION_MARKER,
    RedactedText,
    Redactor,
    redact,
    tail,
)

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


@pytest.mark.parametrize(
    ("text", "redacted"),
    [
        (
            'password = "correct horse battery staple"',
            'password = "[REDACTED:assignment]"',
        ),
        ("secret: 'a b c d e f g h'", "secret: '[REDACTED:assignment]'"),
        ('token="abcdefghij" next', 'token="[REDACTED:assignment]" next'),
        ('password = "abcdefghij', 'password = "[REDACTED:assignment]'),
        ('password="abc\'defghijklmnop"', 'password="[REDACTED:assignment]"'),
        ("secret: 'it\"s a long one'", "secret: '[REDACTED:assignment]'"),
        ('token="abc\\"defghijkl" next', 'token="[REDACTED:assignment]" next'),
    ],
)
def test_a_quoted_value_is_redacted_whole_even_with_spaces(text, redacted):
    assert redact(text).text == redacted


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


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("OPENAI_API_KEY=abcdefgh12345", "OPENAI_API_KEY="),
        ("export DB_PASSWORD=hunter2hunter2", "export DB_PASSWORD="),
        ("client_secret: 'zzzzzzzzzz'", "client_secret: '"),
        ("GITHUB_TOKEN=abcdefghij0123", "GITHUB_TOKEN="),
        ("AWS_SECRET_ACCESS_KEY=abcdefghijkl", "AWS_SECRET_ACCESS_KEY="),
        ("db.password=abcdefghijkl", "db.password="),
        ("tokens: abcdefghijk", "tokens: "),
        ('{"api_key": "abcdefghijk"}', '{"api_key": "'),
        ("service-credentials=abcdefghijkl", "service-credentials="),
    ],
)
def test_assignments_with_prefixed_suffixed_or_quoted_names_are_redacted(text, kept):
    """Pilot 3, redactor finding: `\\b` cannot anchor `OPENAI_API_KEY`
    because `_` is a word character, so prefixed names leaked."""
    out = redact(text)
    assert out.text.startswith(f"{kept}[REDACTED:assignment]")
    assert out.redaction_count == 1


@pytest.mark.parametrize(
    "text",
    ["max_tokens: 24000", "tokenizer=abcdefghijkl", "mytoken=abcdefghijkl"],
)
def test_names_merely_containing_a_keyword_or_short_values_are_left(text):
    assert redact(text).text == text


def test_assignment_matching_stays_linear_on_adversarial_input():
    import time

    start = time.monotonic()
    for text in ("a_" * 200_000, "x-" * 200_000 + "password", "a" * 400_000):
        redact(text)
    assert time.monotonic() - start < 2.0


def test_private_key_redaction_stays_linear_without_end_markers():
    import time

    begin = "-----BEGIN PRIVATE KEY-----\n"
    start = time.monotonic()
    out = redact(begin * 20_000 + "no end marker")
    assert time.monotonic() - start < 2.0
    marker = "[REDACTED:private-key-unterminated]\n"
    assert out.text == marker * 20_000 + "no end marker"
    assert out.redaction_count == 20_000


PAYLOAD = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ"


def test_a_private_key_with_no_end_marker_is_removed_with_its_material():
    text = f"log line\n-----BEGIN RSA PRIVATE KEY-----\n{PAYLOAD}\n{PAYLOAD}"
    out = redact(text)
    assert out.text == "log line\n[REDACTED:private-key-unterminated]"
    assert PAYLOAD not in out.text
    assert out.redaction_count == 1


def test_code_after_an_unterminated_marker_survives():
    """A diff is redacted whole: swallowing to the end of the text hid every
    file after a test that only mentions the BEGIN marker."""
    text = (
        '+    begin = "-----BEGIN PRIVATE KEY-----\\n"\n'
        "+    start = time.monotonic()\n"
        "diff --git a/pyproject.toml b/pyproject.toml\n"
    )
    out = redact(text)
    assert out.text == (
        '+    begin = "[REDACTED:private-key-unterminated]\n'
        "+    start = time.monotonic()\n"
        "diff --git a/pyproject.toml b/pyproject.toml\n"
    )


@pytest.mark.parametrize(
    "material",
    [
        f"{PAYLOAD}\n{PAYLOAD}\nAB==",
        f"Proc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,0123ABCD\n\n{PAYLOAD}\nAB==",
        f'+    "{PAYLOAD}\\n"\n+    "{PAYLOAD}\\n",',
        f"2026-11-07T23:49:41.2Z {PAYLOAD}\n2026-11-07T23:49:41.3Z {PAYLOAD}",
    ],
    ids=["bare", "pem-headers", "quoted-in-a-diff", "timestamped-log"],
)
def test_unterminated_key_material_is_removed_in_any_line_framing(material):
    text = f"-----BEGIN RSA PRIVATE KEY-----\n{material}\nkept()\n"
    out = redact(text)
    assert out.text == "[REDACTED:private-key-unterminated]\nkept()\n"
    assert PAYLOAD not in out.text


def test_a_key_flattened_onto_its_begin_line_is_removed_with_that_line():
    out = redact(f"env KEY=-----BEGIN PRIVATE KEY----- {PAYLOAD}")
    assert out.text == "env KEY=[REDACTED:private-key-unterminated]"


def test_a_short_line_after_key_material_is_kept_unless_it_looks_like_its_end():
    log = f"-----BEGIN EC PRIVATE KEY-----\nT1 {PAYLOAD}\nT2 next step\n"
    assert redact(log).text == "[REDACTED:private-key-unterminated]\nT2 next step\n"


@pytest.mark.parametrize(
    "annotation",
    [
        "known_secrets: tuple[str, ...] = ()",
        "secret_sources: tuple[Callable[[], Sequence[str]], ...] = ()",
        "tokens: Sequence[str]",
        "def f(api_key: Mapping[str, str]) -> None:",
    ],
)
def test_type_annotations_are_not_redacted_as_values(annotation):
    assert redact(annotation).text == annotation


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('token: str = "abcdefghijklmnop"', 'token: str = "[REDACTED:assignment]"'),
        (
            "api_key: Final[str] = 'abcdefghijkl'",
            "api_key: Final[str] = '[REDACTED:assignment]'",
        ),
        (
            "password: str | None = abcdefghij",
            "password: str | None = [REDACTED:assignment]",
        ),
        ("password: Xk9[f$2abcdef", "password: [REDACTED:assignment]"),
        ("token: [abcdefghij]", "token: [REDACTED:assignment]"),
    ],
)
def test_annotated_assignments_and_bracketed_values_are_still_redacted(raw, expected):
    assert redact(raw).text == expected


def test_a_terminated_key_before_an_unterminated_one_is_still_counted():
    out = redact(f"{PRIVATE_KEY}\nkept\n-----BEGIN EC PRIVATE KEY-----\nMIIfake")
    assert out.text == (
        "[REDACTED:private-key]\nkept\n[REDACTED:private-key-unterminated]"
    )
    assert out.redaction_count == 2


def test_each_private_key_block_ends_at_its_own_end_marker():
    out = redact(f"{PRIVATE_KEY}\nkeep me\n{PRIVATE_KEY}")
    assert out.text == "[REDACTED:private-key]\nkeep me\n[REDACTED:private-key]"
    assert out.redaction_count == 2


def test_tail_keeps_whole_lines_and_records_the_full_length():
    full = redact("first line\nsecond line\nthird")
    assert tail(full, 100) is full
    cut = tail(full, 14)
    assert cut.text == "third"
    assert cut.truncated_from == len(full.text)
    assert cut.redaction_count == full.redaction_count


def test_tail_keeps_a_first_line_that_starts_exactly_at_the_cut():
    assert tail(redact("one\ntwo\nthree"), 9).text == "two\nthree"
    assert tail(redact("one\ntwo\nthree"), 8).text == "three"


def test_tail_with_a_zero_budget_is_empty():
    cut = tail(redact("a single nonempty line"), 0)
    assert cut.text == ""
    assert cut.truncated_from == len("a single nonempty line")


def test_tail_of_one_long_line_keeps_its_end():
    assert tail(redact("x" * 10 + "end"), 5).text == "x" * 2 + "end"
