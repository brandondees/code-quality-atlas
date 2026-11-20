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
    FundingSource,
    configured_model,
    funding_byok,
    load_funding_sources,
    noted_funding_source,
    sources_cover,
)
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
    assert source[0].allows("anthropic/claude-sonnet-5.5-20260928")
    assert source[0].allows("anthropic/claude-haiku-4.5")
    assert not source[0].allows("anthropic-lookalike/claude-sonnet-5.5")
    assert not source[0].allows("openai/gpt-4o")
    exact = load_funding_sources(
        _env(_source(model_filter="anthropic/claude-sonnet-5.5"))
    )
    assert exact is not None
    assert exact[0].allows("anthropic/claude-sonnet-5.5")
    assert not exact[0].allows("anthropic/claude-sonnet-5.5-20260928")
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
    with pytest.raises(ValueError, match="short token"):
        load_funding_sources(_env(_source(name="Subs-A")))
    with pytest.raises(ValueError, match="short token"):
        load_funding_sources(_env(_source(name=123)))
    with pytest.raises(ValueError, match="not an ATLAS name"):
        load_funding_sources(_env(_source(key_env=5)))
    with pytest.raises(ValueError, match="filter is not a string"):
        load_funding_sources(_env(_source(model_filter=5)))


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
    eight = load_funding_sources(_env(*many[:8]))
    assert eight is not None
    assert len(eight) == 8
    wide = "a" + "b" * 31
    accepted = load_funding_sources(_env(_source(name=wide)))
    assert accepted is not None
    assert accepted[0].name == wide
    with pytest.raises(ValueError, match="short token"):
        load_funding_sources(_env(_source(name=wide + "c")))
    duplicated = (
        '[{"name": "subs-a", "name": "subs-b", "key_env": "ATLAS_FUNDING_SUBS_A", '
        '"providers": ["anthropic"], "require_zdr": false, '
        '"model_filter": "anthropic/*", "key_ceiling_usd": "195", "byok": true}]'
    )
    with pytest.raises(ValueError, match="repeats the field"):
        load_funding_sources(
            {ENV_FUNDING_SOURCES: duplicated, "ATLAS_FUNDING_SUBS_A": "sk-or-v1-subs-a"}
        )
    pasted = '[{"key": "sk-or-v1-secretsecret"}'
    with pytest.raises(ValueError, match="not JSON") as raised:
        load_funding_sources({ENV_FUNDING_SOURCES: pasted})
    assert "sk-or-v1-secretsecret" not in str(raised.value)


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
    with pytest.raises(ServiceError, match=MODEL_ID):
        config_from_env(
            {
                **base,
                **_env(_source(model_filter="openai/*")),
                "ATLAS_MODEL": MODEL_ID,
            }
        )
    covered = config_from_env(
        {**base, **_env(_source(model_filter="anthropic/*")), "ATLAS_MODEL": MODEL_ID}
    )
    assert covered.provider == "offline"
    with pytest.raises(ServiceError, match="not an ATLAS name"):
        config_from_env({**base, **_env(_source(key_env=5))})
    with pytest.raises(ServiceError, match="filter is not a string"):
        config_from_env({**base, **_env(_source(model_filter=5))})


def test_the_child_readers_default_to_the_process_environment(monkeypatch):
    """The production call passes no mapping. Kills dropping the
    ``os.environ`` fallback, which would make a handed source read as
    unset inside the child."""
    monkeypatch.delenv(ENV_FUNDING_SOURCE, raising=False)
    monkeypatch.delenv(ENV_FUNDING_BYOK, raising=False)
    assert noted_funding_source() == ""
    assert funding_byok() is False
    monkeypatch.setenv(ENV_FUNDING_SOURCE, "subs-a")
    monkeypatch.setenv(ENV_FUNDING_BYOK, "true")
    assert noted_funding_source() == "subs-a"
    assert funding_byok() is True
    monkeypatch.setenv(ENV_FUNDING_BYOK, "TRUE")
    assert funding_byok() is False


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
