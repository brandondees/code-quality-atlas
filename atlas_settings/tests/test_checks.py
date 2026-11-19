# SPDX-License-Identifier: MIT
"""The intake checks the page runs itself: the real egress guard
refusing the hostile hosts (no fake in this file — numeric and
loopback resolution need no network), the model table's contract, and
the key-collision refusal."""

from decimal import Decimal

import pytest

from atlas_reviewer.egress import EgressRefused
from atlas_reviewer.installation_store import InstallationStoreError
from atlas_reviewer.tenant_provider import PricingUnknownError
from atlas_settings import checks
from atlas_settings.phrases import REDACTION_GUARD_TEXTS


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8443/v1",
        "https://localhost/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5/v1",
        "https://192.168.1.1/v1",
        "https://[fc00::1]/v1",
        "https://[fe80::1]/v1",
        "https://[::ffff:127.0.0.1]/v1",
        "http://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://api.example.com/v1?tracking=1",
    ],
)
def test_the_real_egress_check_refuses_the_hostile_shapes(url: str) -> None:
    with pytest.raises(EgressRefused):
        checks.validate_endpoint(url)


def test_the_real_egress_check_refuses_an_unresolvable_host() -> None:
    with pytest.raises(EgressRefused):
        checks.validate_endpoint("https://no-such-host.invalid/v1")


def test_the_real_egress_check_passes_a_public_numeric_host() -> None:
    # A public, non-blocked address resolves without any network: the
    # guard's address-level check alone runs here.
    checks.validate_endpoint("https://93.184.216.34/v1")


def test_the_url_level_half_refuses_before_any_resolution() -> None:
    """The URL-level half — scheme and userinfo — runs before any
    resolution: with a resolver that would allow anything, these shapes
    still refuse. The refusal is the URL check's own, not a resolver
    failure wearing the same clothes."""
    from .harness import default_resolve

    for url in (
        "http://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
    ):
        with pytest.raises(EgressRefused):
            checks.validate_endpoint(url, resolve=default_resolve)


def test_a_public_name_passes_with_the_injected_resolver() -> None:
    def resolve(host: str, port: int):
        import socket

        from atlas_reviewer.egress import Pinned

        assert host == "api.example.com"
        return Pinned(socket.AF_INET, ("93.184.216.34", port or 443))

    checks.validate_endpoint("https://api.example.com/v1", resolve=resolve)


def _terms(model_id: str, prompt: str, completion: str):
    return {
        "data": {
            "id": model_id,
            "pricing": {
                "prompt": prompt,
                "completion": completion,
            },
            "context_length": 8192,
            "top_provider": {"max_completion_tokens": 4096},
        }
    }


def _fake_transport(status: int, payload: bytes):
    class FakeCatalogTransport:
        def request(
            self,
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes | None,
            timeout_s: float,
            max_bytes: int | None = None,
        ):
            from atlas_reviewer.http import HttpResponse

            assert "api/v1/model/" in url
            assert not any("Authorization" in name for name in headers)
            return HttpResponse(status, {}, payload)

    return FakeCatalogTransport()


def test_the_model_table_refuses_an_unknown_model() -> None:
    transport = _fake_transport(404, b'{"error": "no entry"}')
    with pytest.raises(PricingUnknownError):
        checks.validate_model("vendor/not-in-the-table", transport=transport)


def test_the_model_table_read_failure_refuses() -> None:
    class DeadTransport:
        def request(self, *args: object, **kwargs: object):
            raise TimeoutError("timed out")

    with pytest.raises(PricingUnknownError):
        checks.validate_model("vendor/x", transport=DeadTransport())  # type: ignore[arg-type]


def test_the_model_table_read_refuses_a_non_json_answer() -> None:
    transport = _fake_transport(200, b"<html>not json</html>")
    with pytest.raises(PricingUnknownError):
        checks.validate_model("vendor/x", transport=transport)


def test_a_zero_priced_model_is_allowed() -> None:
    rates = checks.validate_model(
        "vendor/zero", transport=_table(_terms("vendor/zero", "0", "0"))
    )
    assert rates == (Decimal(0), Decimal(0))


def test_a_priced_model_returns_its_rates() -> None:
    rates = checks.validate_model(
        "vendor/priced", transport=_table(_terms("vendor/priced", "3", "15"))
    )
    assert rates == (Decimal(3), Decimal(15))


def test_a_negative_rate_refuses() -> None:
    with pytest.raises(PricingUnknownError):
        checks.validate_model(
            "vendor/negative",
            transport=_table(_terms("vendor/negative", "-1", "15")),
        )


def _table(document: dict):
    """The catalog transport answering one fixed document."""
    import json

    return _fake_transport(200, json.dumps(document).encode("utf-8"))


def test_a_wrong_model_id_in_the_entry_refuses() -> None:
    with pytest.raises(PricingUnknownError):
        checks.validate_model(
            "vendor/asked", transport=_table(_terms("vendor/other", "3", "15"))
        )


def test_a_missing_pricing_object_refuses() -> None:
    document = {"data": {"id": "vendor/x", "context_length": 8192}}
    with pytest.raises(PricingUnknownError):
        checks.validate_model("vendor/x", transport=_table(document))


def test_a_key_matching_controller_text_is_refused() -> None:
    # Any fixed phrase is a collision: pick the consent statement's
    # distinctive substring and build a key out of it.
    text = REDACTION_GUARD_TEXTS[0]
    colliding = text[:24]
    assert len(colliding) >= 8
    with pytest.raises(InstallationStoreError, match="collide"):
        checks.check_key_against_controller_text(colliding)


def test_an_ordinary_key_passes_the_collision_check() -> None:
    checks.check_key_against_controller_text("sk-ordinary-key-value-000000")


def test_a_short_key_is_not_held_to_the_collision_check() -> None:
    # Below the length the redaction registers, the collision hazard the
    # check guards does not arise.
    checks.check_key_against_controller_text("short")
