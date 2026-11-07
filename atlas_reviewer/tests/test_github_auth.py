# SPDX-License-Identifier: MIT
"""GitHub App installation tokens: minted in-process, read-only, cached until
shortly before expiry, and the key never leaks into an error."""

import json
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from atlas_reviewer.fakes import StaticToken
from atlas_reviewer.github_auth import READ_PERMISSIONS, AppInstallationTokens
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.ports import BoundaryError
from atlas_reviewer.redact import Redactor

from .helpers import NOW, FakeClock, fake_token

KEY = "-----BEGIN PRIVATE KEY-----\nfake-key-material\n-----END PRIVATE KEY-----"
URL = "https://api.github.com/app/installations/42/access_tokens"


class Minter:
    """Answers each mint with a fresh token expiring `ttl_s` after the clock."""

    def __init__(self, clock, ttl_s=3600, status=201, permissions=None, body=None):
        self.clock, self.ttl_s, self.status = clock, ttl_s, status
        self.permissions = permissions or dict(READ_PERMISSIONS)
        self.body = body
        self.requests = []

    def request(self, method, url, headers, body, timeout_s, max_bytes=None):
        self.requests.append((method, url, dict(headers), json.loads(body)))
        token = fake_token(f"ghs_{len(self.requests)}")
        expires = (self.clock.now() + timedelta(seconds=self.ttl_s)).isoformat()
        payload = self.body or {
            "token": token,
            "expires_at": expires,
            "permissions": self.permissions,
        }
        return HttpResponse(self.status, {}, json.dumps(payload).encode())


def tokens(transport, clock, encode=lambda claims, key: "signed-jwt", **kw):
    return AppInstallationTokens(
        transport, clock, app_id="5648875", private_key=KEY, installation_id=42,
        encode=encode, **kw,
    )  # fmt: skip


def test_mint_requests_read_only_permissions_for_one_repository():
    clock = FakeClock()
    t = Minter(clock)
    token = tokens(t, clock, repositories=("example-app",)).token()
    method, url, headers, body = t.requests[0]
    assert (method, url) == ("POST", URL)
    assert headers["Authorization"] == "Bearer signed-jwt"
    assert body == {
        "permissions": dict(READ_PERMISSIONS),
        "repositories": ["example-app"],
    }
    assert token.startswith("ghs_1")


def test_token_is_cached_until_five_minutes_before_expiry():
    clock = FakeClock()
    t = Minter(clock, ttl_s=3600)
    source = tokens(t, clock)
    first = source.token()
    clock.advance(3600 - 301)
    assert source.token() == first
    assert len(t.requests) == 1
    clock.advance(1)
    second = source.token()
    assert second != first
    assert len(t.requests) == 2
    assert source.secrets() == (KEY, first, second)


def test_jwt_claims_are_backdated_and_short_lived():
    seen = {}

    def encode(claims, key):
        seen.update(claims, key=key)
        return "signed-jwt"

    clock = FakeClock()
    tokens(Minter(clock), clock, encode=encode).token()
    now = int(NOW.timestamp())
    assert seen == {"iat": now - 60, "exp": now + 540, "iss": "5648875", "key": KEY}


def test_real_rs256_signature_verifies_with_the_public_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    clock = FakeClock()
    t = Minter(clock)
    AppInstallationTokens(
        t, clock, app_id="5648875", private_key=pem, installation_id=42
    ).token()
    signed = t.requests[0][2]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        signed,
        private.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == "5648875"
    assert claims["exp"] - claims["iat"] == 600


def test_signing_failure_names_the_error_type_not_the_key():
    clock = FakeClock()
    with pytest.raises(BoundaryError) as info:
        AppInstallationTokens(
            Minter(clock), clock, app_id="1", private_key=KEY, installation_id=42
        ).token()
    assert "could not sign the GitHub App JWT" in str(info.value)
    assert "fake-key-material" not in str(info.value)
    assert info.value.__cause__ is None


@pytest.mark.parametrize(
    "minter,match",
    [
        ({"status": 401}, "HTTP 401"),
        ({"permissions": {"contents": "write", "checks": "read"}}, "not read-only: contents"),
        ({"body": {"token": "t", "expires_at": "2026-11-07T00:00:00Z"}}, "did not report"),
        ({"body": {"expires_at": "2026-11-07T00:00:00Z", "permissions": {}}}, "lacks token"),
        ({"body": {"token": "t", "expires_at": "soon", "permissions": {}}}, "not ISO 8601"),
        ({"body": {"token": "t", "expires_at": "2026-11-07T00:00:00", "permissions": {}}},
         "naive or already past"),
        ({"ttl_s": -1}, "naive or already past"),
    ],
)  # fmt: skip
def test_mint_failures_are_refused(minter, match):
    clock = FakeClock()
    with pytest.raises(BoundaryError, match=match):
        tokens(Minter(clock, **minter), clock).token()


@pytest.mark.parametrize("raw", [b"<html>", b"[]"])
def test_unparseable_mint_responses_are_refused(raw):
    class Raw:
        def request(self, *args, **kwargs):
            return HttpResponse(201, {}, raw)

    with pytest.raises(BoundaryError, match="GitHub App token mint returned"):
        tokens(Raw(), FakeClock()).token()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"app_id": "abc"}, "numeric"),
        ({"installation_id": 0}, "positive"),
        ({"permissions": {"contents": "write"}}, "only read"),
    ],
)
def test_bad_configuration_is_refused_before_any_request(kwargs, match):
    base = {"app_id": "1", "private_key": KEY, "installation_id": 42}
    with pytest.raises(ValueError, match=match):
        AppInstallationTokens(Minter(FakeClock()), FakeClock(), **{**base, **kwargs})


def test_minted_tokens_reach_the_redactor_as_they_are_minted():
    clock = FakeClock()
    source = tokens(Minter(clock), clock)
    redactor = Redactor((), sources=(source.secrets,))
    token = source.token()
    scrubbed = redactor(f"log line with {token} and {KEY}")
    assert token not in scrubbed.text
    assert "fake-key-material" not in scrubbed.text
    assert scrubbed.redaction_count == 2


def test_static_token_is_a_token_source():
    assert StaticToken("abc").token() == "abc"
