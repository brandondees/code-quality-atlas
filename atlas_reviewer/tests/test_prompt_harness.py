# SPDX-License-Identifier: MIT
from atlas_reviewer.harness import DEFAULT_BUNDLE, SkillBundleHarness, load_bundle
from atlas_reviewer.ports import ReviewRequest
from atlas_reviewer.prompt import LoadedLens, UntrustedBlock
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
