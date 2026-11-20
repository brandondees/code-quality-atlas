# SPDX-License-Identifier: MIT
"""The operator funding-source registry (D94). Unset is no registry."""

import json
from decimal import Decimal

import pytest

from atlas_reviewer.funding import (
    _MODEL_ID,
    _PROVIDER,
    ENV_FUNDING_BYOK,
    ENV_FUNDING_SOURCE,
    ENV_FUNDING_SOURCES,
    ENV_MODEL,
    PILOT_KEY_ENV,
    FundingSelector,
    FundingSource,
    configured_model,
    funding_byok,
    key_probe,
    load_funding_sources,
    noted_funding_source,
    sources_cover,
)
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.openrouter import (
    _MODEL_ID as ROUTE_MODEL_ID,
)
from atlas_reviewer.openrouter import (
    _PROVIDER_SLUG,
    MODEL_ID,
)
from atlas_reviewer.openrouter import (
    ENV_MODEL as ROUTE_MODEL_ENV,
)
from atlas_reviewer.ports import (
    KEY_AUTH_REFUSED,
    KEY_OUT_OF_CREDIT,
    BoundaryError,
    KeyRefusedError,
)
from atlas_reviewer.pricing import KeyStatus
from atlas_reviewer.service import ServiceError, config_from_env

SECRET = "webhook-secret-value"


def _source(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "name": "subs-a",
        "key_env": "ATLAS_FUNDING_SUBS_A",
        "providers": ["anthropic"],
        "require_zdr": False,
        "model_filter": "anthropic/*",
        "key_ceiling_usd": "195",
        "byok": True,
    }
    item.update(overrides)
    return item


def _env(*items: dict[str, object], **keys: str) -> dict[str, str]:
    names = {str(item["key_env"]): f"sk-or-v1-{item['name']}" for item in items}
    names.update(keys)
    return {ENV_FUNDING_SOURCES: json.dumps(list(items)), **names}


def test_an_unset_or_blank_setting_is_no_registry():
    """Unset, empty, and whitespace are today's single key. Kills a
    mutant that treats a blank value as a broken document, and one that
    invents a default source when the variable is absent."""
    assert load_funding_sources({}) is None
    assert load_funding_sources({ENV_FUNDING_SOURCES: ""}) is None
    assert load_funding_sources({ENV_FUNDING_SOURCES: "   "}) is None


def test_sources_keep_the_document_order_and_their_fields():
    """Order is the spend order. The fields round-trip as typed values,
    not as the JSON text. Kills a mutant that sorts by name, and one
    that stores the ceiling as a string the preflight cannot compare."""
    first = _source()
    second = _source(
        name="pilot",
        key_env=PILOT_KEY_ENV,
        providers=["google-vertex/global"],
        require_zdr=True,
        model_filter="*",
        key_ceiling_usd=5,
        byok=False,
    )
    loaded = load_funding_sources(_env(first, second))
    assert loaded is not None
    assert [source.name for source in loaded] == ["subs-a", "pilot"]
    subs, pilot = loaded
    assert subs == FundingSource(
        "subs-a",
        "ATLAS_FUNDING_SUBS_A",
        ("anthropic",),
        False,
        "anthropic/*",
        Decimal(195),
        True,
    )
    assert pilot.require_zdr is True
    assert pilot.byok is False
    assert pilot.key_ceiling_usd == Decimal(5)
    assert pilot.providers == ("google-vertex/global",)


def test_a_vendor_prefix_does_not_match_a_lookalike_vendor():
    """``anthropic/*`` matches Anthropic ids and not a vendor whose name
    merely starts with the same letters. Kills a startswith without the
    separating slash."""
    source = load_funding_sources(_env(_source()))
    assert source is not None
    assert source[0].allows("anthropic/claude-sonnet-5.5")
    assert source[0].allows("anthropic/claude-haiku-4.5")
    assert not source[0].allows("anthropic-lookalike/claude-sonnet-5.5")
    assert not source[0].allows("openai/gpt-4o")
    exact = load_funding_sources(
        _env(_source(model_filter="anthropic/claude-sonnet-5.5"))
    )
    assert exact is not None
    assert exact[0].allows("anthropic/claude-sonnet-5.5")
    assert not exact[0].allows("anthropic/claude-haiku-4.5")
    any_model = load_funding_sources(_env(_source(model_filter="*")))
    assert any_model is not None
    assert any_model[0].allows("openai/gpt-4o")


def test_a_string_boolean_is_refused():
    """JSON ``false`` is a boolean. The string ``\"false\"`` is not, and
    ``bool(\"false\")`` would be True. Kills that coercion on both flags."""
    for field in ("require_zdr", "byok"):
        with pytest.raises(ValueError, match=field):
            load_funding_sources(_env(_source(**{field: "false"})))


def test_a_tenant_name_and_a_non_funding_key_variable_are_refused():
    """The operator list cannot name an installation credential, and it
    cannot point a source at the GitHub key or at the handoff variables.
    Kills a mutant that accepts any ``ATLAS_`` name."""
    refused = (
        _source(key_env="ATLAS_TENANT_MODEL_KEY"),
        _source(key_env="ATLAS_GITHUB_APP_PRIVATE_KEY"),
        _source(key_env="ATLAS_FUNDING_SOURCE"),
        _source(key_env="ATLAS_SPRITES_TOKEN"),
        _source(name="atlas-tenant-a"),
    )
    for item in refused:
        with pytest.raises(ValueError):
            load_funding_sources(_env(item))


def test_a_missing_key_variable_duplicate_or_extra_field_is_refused():
    env = _env(_source())
    del env["ATLAS_FUNDING_SUBS_A"]
    with pytest.raises(ValueError, match="unset"):
        load_funding_sources(env)
    blank = _env(_source())
    blank["ATLAS_FUNDING_SUBS_A"] = "  "
    with pytest.raises(ValueError, match="unset"):
        load_funding_sources(blank)
    twice = _source()
    with pytest.raises(ValueError, match="repeats the name"):
        load_funding_sources(_env(twice, _source(key_env="ATLAS_FUNDING_SUBS_B")))
    with pytest.raises(ValueError, match="repeats the key"):
        load_funding_sources(
            _env(_source(), _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_A"))
        )
    extra = _source()
    extra["limit_reset"] = "monthly"
    with pytest.raises(ValueError, match="extra"):
        load_funding_sources(_env(extra))
    missing = _source()
    del missing["byok"]
    with pytest.raises(ValueError, match="missing"):
        load_funding_sources(_env(missing))


def test_a_malformed_document_is_refused():
    """Not JSON, not an array, an empty array, and a document past the
    size cap all fail closed. Kills treating ``[]`` as unset, and
    treating a JSON object as one source."""
    for raw in ("{", "null", "{}", "[]", '"subs-a"', "[1]"):
        with pytest.raises(ValueError):
            load_funding_sources({ENV_FUNDING_SOURCES: raw})
    at_cap = "x" * 8192
    with pytest.raises(ValueError, match="not JSON"):
        load_funding_sources({ENV_FUNDING_SOURCES: at_cap})
    with pytest.raises(ValueError, match="longer"):
        load_funding_sources({ENV_FUNDING_SOURCES: at_cap + "x"})
    many = [
        _source(name=f"s{index}", key_env=f"ATLAS_FUNDING_K{index}")
        for index in range(9)
    ]
    with pytest.raises(ValueError, match="limit"):
        load_funding_sources(_env(*many))


def test_a_bad_provider_filter_or_ceiling_is_refused():
    with pytest.raises(ValueError, match="provider"):
        load_funding_sources(_env(_source(providers=[])))
    with pytest.raises(ValueError, match="provider"):
        load_funding_sources(_env(_source(providers=["Anthropic"])))
    with pytest.raises(ValueError, match="repeats the provider"):
        load_funding_sources(_env(_source(providers=["anthropic", "anthropic"])))
    with pytest.raises(ValueError, match="filter"):
        load_funding_sources(_env(_source(model_filter="anthropic")))
    with pytest.raises(ValueError, match="filter"):
        load_funding_sources(_env(_source(model_filter="google-vertex/global/*")))
    for ceiling in (0, -1, "195.00.1", True, 195.5, "10000.01", "1e3", "1_000"):
        with pytest.raises(ValueError, match="ceiling"):
            load_funding_sources(_env(_source(key_ceiling_usd=ceiling)))
    loaded = load_funding_sources(_env(_source(key_ceiling_usd="10000")))
    assert loaded is not None
    assert loaded[0].key_ceiling_usd == Decimal(10000)


def test_the_provider_slug_grammar_matches_the_route_layer():
    """A slug, a model id, and the model variable the registry accepts
    are the ones the route layer accepts. Kills a second grammar that
    drifts from ``openrouter``."""
    assert _PROVIDER.pattern == _PROVIDER_SLUG.pattern
    assert _MODEL_ID.pattern == ROUTE_MODEL_ID.pattern
    assert ENV_MODEL == ROUTE_MODEL_ENV


def test_no_source_matching_the_configured_model_is_a_boot_failure():
    """A list that cannot serve the model the service will ask for stops
    the process. Kills skipping the coverage check, which would boot a
    deployment that can never select a source."""
    sources = load_funding_sources(_env(_source(model_filter="openai/*")))
    assert sources is not None
    with pytest.raises(ValueError, match=MODEL_ID):
        sources_cover(sources, MODEL_ID)
    with pytest.raises(ValueError, match="not an OpenRouter model id"):
        configured_model({"ATLAS_MODEL": "claude"}, MODEL_ID)
    with pytest.raises(ValueError, match="not an OpenRouter model id"):
        sources_cover(sources, "claude")
    assert configured_model({}, MODEL_ID) == MODEL_ID
    base = {
        "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
        "ATLAS_SERVICE_PROVIDER": "offline",
    }
    with pytest.raises(ServiceError, match="ATLAS_TENANT"):
        config_from_env({**base, **_env(_source(key_env="ATLAS_TENANT_MODEL_KEY"))})
    built = config_from_env({**base, **_env(_source())})
    assert built.provider == "offline"


def test_a_noted_source_name_is_the_token_and_byok_is_only_the_word_true():
    assert noted_funding_source({}) == ""
    assert noted_funding_source({ENV_FUNDING_SOURCE: "subs-a"}) == "subs-a"
    assert noted_funding_source({ENV_FUNDING_SOURCE: "Subs-A"}) == ""
    assert noted_funding_source({ENV_FUNDING_SOURCE: "subs a"}) == ""
    assert funding_byok({}) is False
    assert funding_byok({ENV_FUNDING_BYOK: "true"}) is True
    assert funding_byok({ENV_FUNDING_BYOK: "false"}) is False
    assert funding_byok({ENV_FUNDING_BYOK: "TRUE"}) is False
    assert funding_byok({ENV_FUNDING_BYOK: "1"}) is False


def _credit(limit: str = "50", remaining: str = "40") -> KeyStatus:
    return KeyStatus(
        limit=Decimal(limit),
        limit_remaining=Decimal(remaining),
        usage=Decimal(0),
        counts_byok=True,
    )


def _selector(env: dict[str, str], probe) -> FundingSelector:
    sources = load_funding_sources(env)
    assert sources is not None
    return FundingSelector(sources, env, probe, MODEL_ID)


def test_claim_time_skips_a_dry_key_and_does_not_probe_a_model_the_source_cannot_serve():
    """The first source with remaining credit is the one the review
    uses. A source whose filter misses the model is not probed, and a
    key over its ceiling is not a refusal. Kills probing every key, and
    treating an over-ceiling key as out of credit."""
    calls: list[str] = []

    def probe(key: str) -> KeyStatus:
        calls.append(key)
        if key == "sk-or-v1-subs-a":
            return _credit(remaining="0")
        if key == "sk-or-v1-high":
            return _credit(limit="500")
        return _credit()

    env = _env(
        _source(),
        _source(name="other", key_env="ATLAS_FUNDING_OTHER", model_filter="openai/*"),
        _source(name="high", key_env="ATLAS_FUNDING_HIGH", key_ceiling_usd="195"),
        _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_B"),
    )
    selection = _selector(env, probe).choose()
    assert selection.choice is not None
    assert selection.choice.name == "subs-b"
    assert selection.choice.key == "sk-or-v1-subs-b"
    assert selection.refusal == ""
    assert calls == ["sk-or-v1-subs-a", "sk-or-v1-high", "sk-or-v1-subs-b"]


def test_every_dry_or_refused_source_is_a_credit_or_auth_refusal_with_no_child_source():
    """When nothing can pay, the selection carries the D92 cause and no
    choice. A 401 is auth refused. A later claim does not probe a key
    already known to be dry. Kills posting a choice anyway, and forgetting
    the refusal so the same dry key is probed again."""
    env = _env(_source(), _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_B"))
    calls: list[str] = []

    def dry(key: str) -> KeyStatus:
        calls.append(key)
        return _credit(remaining="0")

    selector = _selector(env, dry)
    selection = selector.choose()
    assert selection.choice is None
    assert selection.refusal == KEY_OUT_OF_CREDIT
    assert selection.error == ""
    assert selector.choose().refusal == KEY_OUT_OF_CREDIT
    assert calls == ["sk-or-v1-subs-a", "sk-or-v1-subs-b"]

    def refused(key: str) -> KeyStatus:
        raise KeyRefusedError("OpenRouter HTTP 401", review_error=KEY_AUTH_REFUSED)

    auth = _selector(env, refused).choose()
    assert auth.choice is None
    assert auth.refusal == KEY_AUTH_REFUSED
    assert "sk-or" not in auth.refusal


def test_a_probe_that_fails_does_not_mark_the_source_unavailable():
    """A 500 is not a refusal. The next claim can still choose that
    source. When it is the only source, the selection is an error with
    no D92 cause. Kills treating a transient failure as out of credit."""
    env = _env(_source())
    calls = {"n": 0}

    def probe(key: str) -> KeyStatus:
        calls["n"] += 1
        if calls["n"] == 1:
            raise BoundaryError(
                "OpenRouter HTTP 500 for https://openrouter.ai/api/v1/key"
            )
        return _credit()

    selector = _selector(env, probe)
    first = selector.choose()
    assert first.choice is None
    assert first.refusal == ""
    assert first.error
    second = selector.choose()
    assert second.choice is not None
    assert second.choice.name == "subs-a"


def test_marking_a_source_refused_makes_the_next_claim_use_the_following_one():
    env = _env(_source(), _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_B"))
    selector = _selector(env, lambda key: _credit())
    first = selector.choose()
    assert first.choice is not None
    assert selector.mark_refused(first.choice.name, KEY_AUTH_REFUSED) is True
    second = selector.choose()
    assert second.choice is not None
    assert second.choice.name == "subs-b"
    assert selector.mark_refused("subs-b") is False


def test_the_key_probe_classifies_401_and_402_and_never_echoes_the_body(monkeypatch):
    """The live probe's error is the status and the URL. The response
    body and the bearer token stay out of it. A 500 is a boundary
    error, not a key refusal. Kills classifying every non-200 as out of
    credit, and putting the body on the error."""
    secret = "sk-or-v1-probe-secret"
    seen: dict[str, object] = {}

    class Transport:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def request(self, method, url, headers, body, timeout_s):
            seen["method"] = method
            seen["url"] = url
            seen["authorization"] = headers["Authorization"]
            status = seen.get("status", 200)
            return HttpResponse(status, {}, seen.get("payload", b"{}"))

    monkeypatch.setattr("atlas_reviewer.funding.UrllibTransport", Transport)
    payload = json.dumps(
        {
            "data": {
                "limit": 50,
                "limit_remaining": 40,
                "usage": 10,
                "include_byok_in_limit": True,
            }
        }
    ).encode()
    seen["payload"] = payload
    status = key_probe(secret)
    assert status.limit_remaining == Decimal(40)
    assert seen["method"] == "GET"
    assert seen["url"] == "https://openrouter.ai/api/v1/key"
    assert seen["authorization"] == f"Bearer {secret}"
    seen["status"] = 401
    seen["payload"] = b'{"error":"the body names the key sk-or-v1-probe-secret"}'
    with pytest.raises(KeyRefusedError) as refused:
        key_probe(secret)
    assert refused.value.review_error == KEY_AUTH_REFUSED
    assert secret not in str(refused.value)
    assert "the body" not in str(refused.value)
    seen["status"] = 402
    with pytest.raises(KeyRefusedError) as dry:
        key_probe(secret)
    assert dry.value.review_error == KEY_OUT_OF_CREDIT
    seen["status"] = 500
    with pytest.raises(BoundaryError) as failed:
        key_probe(secret)
    assert not isinstance(failed.value, KeyRefusedError)


def test_a_funding_key_is_scrubbed_and_boot_does_not_probe(tmp_path, monkeypatch):
    """The subscription key is a secret the service log scrubs, and
    building the service does not call the key endpoint. Kills scrubbing
    only today's pilot variable, and probing at boot."""
    from atlas_reviewer.service import (
        ReviewServer,
        ServiceConfig,
        Worker,
        _child_secrets,
        _service_secrets,
        serve,
    )

    env = _env(_source())
    env["ATLAS_FUNDING_SUBS_A"] = "sk-or-v1-subscription-secret"
    assert "sk-or-v1-subscription-secret" in _child_secrets(env)
    assert "sk-or-v1-subscription-secret" in _service_secrets(
        ServiceConfig(secret=SECRET, allowlist=frozenset({"o/r"})), env
    )
    captured: dict[str, object] = {}
    real_init = Worker.__init__

    def init(self, *args, **kwargs):
        captured["funding"] = kwargs.get("funding")
        captured["tenant_active"] = kwargs.get("tenant_active")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(Worker, "__init__", init)
    monkeypatch.setattr(Worker, "start", lambda self: None)
    monkeypatch.setattr(Worker, "stop", lambda self, timeout=30: None)

    def fake_init(self, config, board, log):
        self.config = config
        self.board = board
        self.log = log

    monkeypatch.setattr(ReviewServer, "__init__", fake_init)
    monkeypatch.setattr(ReviewServer, "serve_forever", lambda self: None)
    monkeypatch.setattr(ReviewServer, "server_close", lambda self: None)

    def probe(key):
        raise AssertionError(f"boot probed {key}")

    monkeypatch.setattr("atlas_reviewer.service.key_probe", probe)
    boot = {
        "ATLAS_GITHUB_WEBHOOK_SECRET": SECRET,
        "ATLAS_SERVICE_PROVIDER": "offline",
        "ATLAS_REVIEWER_STATE_DIR": str(tmp_path),
        **env,
    }
    assert serve(config_from_env(boot), boot) == 0
    assert captured["funding"] is not None
    tenant_active = captured["tenant_active"]
    assert callable(tenant_active)
    assert tenant_active() is False
