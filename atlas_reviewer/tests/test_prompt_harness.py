# SPDX-License-Identifier: MIT
import re

from atlas_reviewer.budget import input_token_bound
from atlas_reviewer.harness import (
    DEFAULT_BUNDLE,
    NONCE_CHARS,
    PICK_REPLY_CHARS,
    SkillBundleHarness,
    load_bundle,
)
from atlas_reviewer.ports import PickRequest, ReviewRequest
from atlas_reviewer.prompt import LoadedLens, RepoText, UntrustedBlock
from atlas_reviewer.providers import OfflineProvider
from atlas_reviewer.redact import Redactor, redact

from .helpers import HEAD, fake_token

NONCE = "n0nce"


def test_harness_uses_the_repo_skill_bundle_and_redacts_model_output():
    class EchoingProvider(OfflineProvider):
        def complete(self, prompt):
            super().complete(prompt)
            return "leaked " + fake_token("ghs_")

    provider = EchoingProvider()
    harness = SkillBundleHarness(
        provider, load_bundle(), Redactor(), nonce=lambda: NONCE
    )
    narrative = harness.review(
        ReviewRequest("o/r", 1, HEAD, (UntrustedBlock("diff", redact("x")),))
    )
    assert "ghs_" not in narrative.text.text
    assert (narrative.harness, narrative.provider) == ("skill-bundle", "offline")
    (prompt,) = provider.prompts
    assert "name: reviewing-a-change" in prompt.system
    assert f"o/r pull request #1 at {HEAD}" in prompt.user
    assert DEFAULT_BUNDLE.name == "SKILL.md"


def test_the_harness_forwards_lenses_to_the_provider():
    provider = OfflineProvider()
    harness = SkillBundleHarness(provider, "B", Redactor(), nonce=lambda: NONCE)
    harness.review(
        ReviewRequest(
            "o/r",
            1,
            HEAD,
            (UntrustedBlock("diff", redact("x")),),
            (LoadedLens("a-lens", "CHECKLIST A"),),
            "included: a-lens",
        )
    )
    (prompt,) = provider.prompts
    assert "CHECKLIST A" in prompt.system


def test_pick_runs_the_picker_procedure_and_redacts_and_caps_its_reply():
    class LongReply(OfflineProvider):
        def complete(self, prompt):
            super().complete(prompt)
            return fake_token("ghs_") + " " + "y" * (PICK_REPLY_CHARS * 2)

    provider = LongReply()
    harness = SkillBundleHarness(
        provider, "REVIEW BUNDLE", Redactor(), nonce=lambda: NONCE, picker="PICKER"
    )
    reply = harness.pick(
        PickRequest(
            "o/r",
            7,
            HEAD,
            "PICK INSTRUCTIONS",
            (UntrustedBlock("paths", RepoText("src/a.py")),),
        )
    )
    assert "ghs_" not in reply
    assert "[REDACTED" in reply
    assert len(reply) < PICK_REPLY_CHARS + 200
    (prompt,) = provider.prompts
    assert prompt.system.startswith("PICK INSTRUCTIONS\n\n")
    assert prompt.system.endswith("--- lens picker ---\nPICKER")
    assert "REVIEW BUNDLE" not in prompt.system
    assert f"o/r pull request #7 at {HEAD}" in prompt.user
    assert f'<untrusted-data id="{NONCE}" label="paths">\nsrc/a.py\n' in prompt.user


def test_usage_lines_are_the_providers():
    provider = OfflineProvider()
    harness = SkillBundleHarness(provider, "B", Redactor(), nonce=lambda: NONCE)
    harness.review(ReviewRequest("o/r", 1, HEAD, ()))
    assert harness.usage_lines() == (
        "offline provider: 1 prompt(s) seen, no model calls, $0.00",
    )


def test_the_default_nonce_is_fresh_hex_of_the_measured_length():
    provider = OfflineProvider()
    harness = SkillBundleHarness(provider, "B", Redactor())
    request = ReviewRequest("o/r", 1, HEAD, (UntrustedBlock("d", RepoText("x")),))
    harness.review(request)
    harness.review(request)
    nonces = [re.search(r'id="([^"]*)"', p.user).group(1) for p in provider.prompts]
    assert all(re.fullmatch(f"[0-9a-f]{{{NONCE_CHARS}}}", n) for n in nonces)
    assert nonces[0] != nonces[1]


def _sent_tokens(nonce: str, diff: str) -> tuple[int, int]:
    """(prompt_tokens' measurement, bound of the prompt review actually sent)."""
    provider = OfflineProvider()
    harness = SkillBundleHarness(provider, "B", Redactor(), nonce=lambda: nonce)
    request = ReviewRequest("o/r", 1, HEAD, (UntrustedBlock("diff", RepoText(diff)),))
    measured = harness.prompt_tokens(request)
    harness.review(request)
    (prompt,) = provider.prompts
    return measured, input_token_bound(prompt.system + prompt.user)


def test_prompt_tokens_is_not_undercounted_by_zero_runs_in_the_diff():
    # Each 16-zero run would be swapped for the 15-byte nonce marker if the
    # measurement used an all-zero nonce, while the real nonce leaves it alone.
    measured, sent = _sent_tokens("0123456789abcdef", "+" + "0" * 16 * 2_000 + "\n")
    assert measured == sent


def test_prompt_tokens_bounds_a_real_nonce_that_does_occur_in_the_diff():
    nonce = "fedcba9876543210"
    measured, sent = _sent_tokens(nonce, f"+{nonce * 50}\n")
    assert measured == sent + 50
