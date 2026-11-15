# SPDX-License-Identifier: MIT
import base64

import pytest

from atlas_reviewer.committed_secrets import scan_diff
from atlas_reviewer.redact import (
    TRUNCATION_MARKER,
    RedactedText,
    Redactor,
    SecretHit,
    detect_secrets,
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


SPRITES_TOKEN = "personal/4321/9876/0123456789abcdef0123456789"


def test_a_sprites_token_shape_is_redacted_and_reported():
    """Issue #663: no pattern covered the controller's Sprites token, so a
    value the controller does not hold survived redaction. The shape is the
    one the operator confirmed the deployed token has -- four
    slash-separated segments `<org slug>/<numeric org id>/<token id>/<secret>`,
    every segment `[A-Za-z0-9_-]`, only the second all digits; the value
    here is synthetic."""
    result = redact(f"token {SPRITES_TOKEN} after")
    assert SPRITES_TOKEN not in result.text
    assert result.text == "token [REDACTED:sprites-token] after"
    assert result.redaction_count == 1
    scan = detect_secrets(f"auth = {SPRITES_TOKEN}\n")
    assert scan.hits == (SecretHit("sprites-token", 1),)
    assert scan.values == (SPRITES_TOKEN,)


@pytest.mark.parametrize(
    "token",
    [
        "acme/1/t/abcd1234efgh",  # a one-digit org id is a token too
        "acme/123/tok_9/abcdefgh-ij9kl_mnop",  # a three-digit org id
        "acme/5/t/abcd1234",  # an eight-character secret is the floor
        "a-long-org-slug/4321/tok_1234567890/abcd1234efgh5678",
        "personal/4321/9876/0123456789abcdef0123456789",
    ],
)
def test_sprites_token_ids_and_slugs_of_any_length_are_redacted(token):
    out = redact(f"bearer {token}")
    assert token not in out.text
    assert out.text == "bearer [REDACTED:sprites-token]"
    assert out.redaction_count == 1


def test_a_seven_character_secret_segment_is_not_a_sprites_token():
    assert redact("token acme/1/t/abcd123").text == "token acme/1/t/abcd123"


TOKEN = "personal/4321/9876/0123456789abcdef0123456789"


@pytest.mark.parametrize(
    "line",
    [
        TOKEN,
        f"Bearer {TOKEN}",
        f"ATLAS_SPRITES_TOKEN={TOKEN}",
        f'{{"t": "{TOKEN}"}}',
        f"'{TOKEN}'",
        f"--token {TOKEN}",
    ],
)
def test_a_token_is_redacted_in_every_position_it_appears_in(line):
    """The boundary accepts a token standing alone and after the separators
    it really follows: whitespace, `=`, `:` and a quote (review round 2 of
    PR #687)."""
    out = redact(line)
    assert "4321" not in out.text
    assert "[REDACTED:sprites-token]" in out.text


@pytest.mark.parametrize(
    "text",
    [
        (
            "https://github.com/o/r/pull/687/commits/"
            "0123456789abcdef0123456789abcdef01234567"
        ),
        "https://github.com/o/r/actions/runs/43653737695/job/12345678901",
        "https://api.github.com/repos/o/r/issues/123/comments/4567890123",
        "https://gitlab.com/g/p/-/merge_requests/42/diffs/abc12345678",
        (
            "https://files.pythonhosted.org/packages/45/ab/"
            "0123456789abcdef0123456789abcdef01/requests-2.31.0-py3-none-any.whl"
        ),
        "https://example.com/2026/11/14/report2026",
        "src/app/2/components/Button2Base.tsx",
        "node_modules/@types/node/16/fs/promises1.d.ts",
        "acme/v2/tok_9/abcdefg1",
    ],
)
def test_a_url_or_path_is_not_a_sprites_token(text):
    """Review round 2 of PR #687, Minor 1: the match may not start where a
    URL path's segments begin (after `/`, `.`, `-` or `_`), so commit and
    job links, wheel URLs and dated paths are not findings; and the second
    segment must be all digits (`acme/v2/...` is not)."""
    assert redact(text).text == text
    assert detect_secrets(text).hits == ()


def test_a_diff_with_url_shapes_gets_no_committed_secret_finding():
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,2 +1,4 @@\n"
        " see the run\n"
        "+https://github.com/o/r/pull/687/commits/"
        "0123456789abcdef0123456789abcdef01234567\n"
        "+https://files.pythonhosted.org/packages/45/ab/"
        "0123456789abcdef0123456789abcdef01/requests-2.31.0-py3-none-any.whl\n"
    )
    scan = scan_diff(diff)
    assert scan.findings == ()
    assert scan.values == ()


@pytest.mark.parametrize(
    "text",
    [
        "http://www.w3.org/2001/XMLSchema-instance",
        "/org/123/repositories",
        "https://api.example.com/org/42/members-list",
        "repos/123/issues/comments",
        "api/2024/users/list",
        "my-org//tok9/abcd1234efgh",
        "my-org/tok_1234/abcdef0123456789abcdef",
        "w3.org/2000/svg",
        "borg/1/abcdefgh",
    ],
)
def test_text_merely_shaped_like_a_sprites_token_survives(text):
    """A token is four segments with a numeric second one and a secret that
    carries a digit; the CLI docs' three-segment example, an empty org id,
    and ordinary four-segment paths are not tokens."""
    assert redact(text).text == text


def test_a_pom_xml_diff_with_the_schema_namespace_gets_no_finding():
    """Review round 1 of PR #687: the first pattern flagged the standard
    XML-schema namespace in every Maven pom.xml, XSD or WSDL diff. The
    scanner must report none."""
    diff = (
        "diff --git a/pom.xml b/pom.xml\n"
        "--- a/pom.xml\n"
        "+++ b/pom.xml\n"
        "@@ -0,0 +1,3 @@\n"
        '+<?xml version="1.0"?>\n'
        '+<project xmlns="http://maven.apache.org/POM/4.0.0"\n'
        '+         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    )
    scan = scan_diff(diff)
    assert scan.findings == ()
    assert scan.values == ()


def test_a_seven_character_value_is_below_the_scrub_floor_and_an_eight_is_not():
    """Review round 1 of PR #687, mutants R1/R2: the 8-character floor on a
    known value is pinned from both sides."""
    eight = Redactor(("abcdefgh",))("value abcdefgh kept")
    assert eight.text == "value [REDACTED:controller-credential] kept"
    seven = Redactor(("abcdefg",))("value abcdefg kept")
    assert seven.text == "value abcdefg kept"
    assert seven.redaction_count == 0


def test_known_credentials_are_scrubbed_in_base64_and_hex():
    """Issue #663: the known-value scrub was an exact substring replace, so
    a log that carried the controller's credential base64- or hex-encoded
    kept it. Every encoding of the value is scrubbed under the same
    label."""
    secret = "org/123/plainsecretvalue"
    raw = secret.encode()
    forms = {
        "raw": secret,
        "base64": base64.b64encode(raw).decode(),
        "base64url": base64.urlsafe_b64encode(raw).decode(),
        "hex": raw.hex(),
    }
    out = Redactor((secret,))(f"raw {secret} b64 {forms['base64']} hex {forms['hex']}")
    assert out.text == (
        "raw [REDACTED:controller-credential]"
        " b64 [REDACTED:controller-credential]"
        " hex [REDACTED:controller-credential]"
    )
    assert out.redaction_count == 3
    flagged = Redactor(flagged=(secret,))(f"quoted b64 {forms['base64']}")
    assert forms["base64"] not in flagged.text
    assert flagged.redaction_count == 1


ENCODED_VALUE = "org/123/~~??value"
ENCODED_RAW = ENCODED_VALUE.encode()
ENCODED_STD = "b3JnLzEyMy9+fj8/dmFsdWU="
ENCODED_URL = "b3JnLzEyMy9-fj8_dmFsdWU="


def test_every_encoding_form_of_a_known_value_is_scrubbed():
    """Review round 1 of PR #687, Minor 2: unpadded base64, upper-case hex,
    the percent-encoded form and the JSON-escaped form are scrubbed too.
    This value's standard and URL-safe base64 differ and need padding, so
    neither variant can stand in for the other."""
    out = Redactor((ENCODED_VALUE,))(
        f"{ENCODED_STD} {ENCODED_STD.rstrip('=')} {ENCODED_URL}"
        f" {ENCODED_URL.rstrip('=')} {ENCODED_RAW.hex()}"
        f" {ENCODED_RAW.hex().upper()}"
        " org%2F123%2F~~%3F%3Fvalue org\\/123\\/~~??value"
    )  # fmt: skip
    assert out.text == " ".join(["[REDACTED:controller-credential]"] * 8)
    assert out.redaction_count == 8
    # The padded form is cut whole: no "=" survives the replacement.
    padded = Redactor((ENCODED_VALUE,))(f"token {ENCODED_STD}")
    assert padded.text == "token [REDACTED:controller-credential]"


def test_overlapping_known_values_replace_longest_first():
    """Review round 1 of PR #687, mutant E5: when one known value contains
    another, the longer is replaced first, so the shorter's replacement
    cannot chop the longer and leave its tail."""
    out = Redactor(("abcdefgh", "abcdefgh1234"))("token abcdefgh1234")
    assert out.text == "token [REDACTED:controller-credential]"
    assert out.redaction_count == 1


def test_a_value_with_undecodable_bytes_is_scrubbed_not_fatal():
    """Review round 1 of PR #687, Nit 3: a known secret read from the
    environment can carry bytes no UTF-8 decode accepts. Redaction must
    never crash on one."""
    import os

    value = os.fsdecode(b"tok\xff\xfeen1234567")
    out = Redactor((value,))(f"token {value} after")
    assert value not in out.text
    assert out.redaction_count == 1


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


def test_tail_keeps_the_truncated_end_of_an_overlong_last_line():
    """A log's last line carries the failure. When that line, including its
    trailing newline, is longer than the budget, trimming to the next whole
    line would leave nothing."""
    cut = tail(redact("x" * 100 + "\n"), 10)
    assert cut.text == "x" * 9 + "\n"
    assert cut.truncated_from == 101
    longer = "short\n" + "y" * 100 + "\n"
    assert tail(redact(longer), 10).text == "y" * 9 + "\n"


def test_detection_reports_label_and_line_never_the_value():
    text = 'x = 1\ntoken: str = "abcdefghijklmnop"\n'
    scan = detect_secrets(text)
    assert scan.hits == (SecretHit("assignment", 2),)
    assert "abcdefghijklmnop" not in repr(scan)
    assert scan.values == ("abcdefghijklmnop",)


def test_an_unterminated_key_and_a_bare_marker_are_both_reported():
    text = (
        f"-----BEGIN RSA PRIVATE KEY-----\n{PAYLOAD}\nkept()\n"
        'begin = "-----BEGIN PRIVATE KEY-----"\n'
    )
    scan = detect_secrets(text)
    assert scan.hits == (
        SecretHit("private-key", 1),
        SecretHit("private-key-marker", 4),
    )
    assert scan.values == (PAYLOAD,)


def test_a_terminated_key_and_known_token_formats_are_reported():
    token = fake_token("ghp_")
    text = f"{PRIVATE_KEY.replace('MIIfake', PAYLOAD)}\nauth = {token}\n"
    labels = [(h.label, h.line) for h in detect_secrets(text).hits]
    assert labels == [("private-key", 1), ("github-token", 4)]


@pytest.mark.parametrize(
    "code",
    [
        "token = get_token()",
        "api_key = settings.API_KEY",
        'password = f"{user}:{pw}"',
        'secret = "please enter your secret"',
        "known_secrets: tuple[str, ...] = ()",
        "token = token_source",
        "password = user_password_hash",
        'password = "[REDACTED:assignment]"',
    ],
)
def test_code_that_only_names_a_secret_is_not_reported(code):
    assert detect_secrets(code).hits == ()


def test_unquoted_config_values_and_one_hit_per_line_and_label():
    scan = detect_secrets(
        "password: hunter2hunter2\nsecret=abc123def456 token=xyz789uvw012\n"
        "password = correct-horse-battery-staple"
    )
    assert scan.hits == tuple(SecretHit("assignment", n) for n in (1, 2, 3))
    assert scan.values == (
        "hunter2hunter2",
        "abc123def456",
        "xyz789uvw012",
        "correct-horse-battery-staple",
    )


def test_key_material_on_diff_lines_is_also_kept_without_the_line_marker():
    line = "+" + PAYLOAD.splitlines()[0]
    scan = detect_secrets(f"+-----BEGIN PRIVATE KEY-----\n{line}\n")
    assert scan.hits == (SecretHit("private-key", 1),)
    assert line in scan.values and line[1:] in scan.values


def test_detection_never_changes_the_text():
    text = f'-----BEGIN PRIVATE KEY-----\n{PAYLOAD}\ntoken: str = "abcdefghijklmnop"'
    before = str(text)
    detect_secrets(text)
    assert text == before


def test_an_already_redacted_value_keeps_its_label_and_is_counted_once():
    token = fake_token("ghp_")
    out = redact(f"token: {token}")
    assert out.text == "token: [REDACTED:github-token]"
    assert out.redaction_count == 1
    quoted = redact(f'password = "{token}"')
    assert quoted.text == 'password = "[REDACTED:github-token]"'
    assert quoted.redaction_count == 1


def test_a_quoted_passphrase_with_spaces_is_redacted_but_not_reported():
    """Redaction scrubs it (a runtime log must not keep it). Detection does
    not report it: a sentence in source would be a false finding."""
    text = 'password = "correct horse battery staple"'
    assert redact(text).text == 'password = "[REDACTED:assignment]"'
    assert detect_secrets(text).hits == ()


def test_flagged_values_are_scrubbed_under_their_own_label():
    out = Redactor(flagged=("abcdefghijklmnop",))("the model quoted abcdefghijklmnop")
    assert out.text == "the model quoted [REDACTED:possible-committed-secret]"
    assert out.redaction_count == 1
