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
    FundingChoice,
    FundingSelection,
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
    with pytest.raises(ValueError, match="tenant credential"):
        load_funding_sources(_env(_source(key_env="ATLAS_TENANT_MODEL_KEY")))
    refused = (
        _source(key_env="ATLAS_GITHUB_APP_PRIVATE_KEY"),
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
    treating a JSON object as one source. The token-valid key cases
    kill the interpolation mutant: restoring ``!r`` on a repeated name,
    field, or provider slug, or restoring ``sorted(extra)``, puts that
    key in the refusal, and restoring a key variable or the model id
    does the same for those refusals."""
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
    secret = "sk-or-v1-secretsecret"
    for field, value in (
        ("model_filter", secret),
        ("key_ceiling_usd", secret),
        ("name", f"{secret}!"),
        ("providers", [f"{secret}!"]),
        ("require_zdr", secret),
        ("byok", secret),
    ):
        with pytest.raises(ValueError) as echoed:
            load_funding_sources(_env(_source(**{field: value})))
        assert secret not in str(echoed.value)
    # ``secret`` matches the name and slug grammars, so it reaches the
    # duplicate-name, duplicate-slug, duplicate-field, and extra-field
    # refusals instead of failing the grammar first.
    named = _source(name=secret)
    with pytest.raises(ValueError, match="repeats the name") as echoed:
        load_funding_sources(
            _env(named, _source(name=secret, key_env="ATLAS_FUNDING_SUBS_B"))
        )
    assert secret not in str(echoed.value)
    with pytest.raises(ValueError, match="repeats the provider") as echoed:
        load_funding_sources(_env(_source(providers=[secret, secret])))
    assert secret not in str(echoed.value)
    repeated_field = (
        '[{"' + secret + '": "a", "' + secret + '": "b", "name": "subs-a"}]'
    )
    with pytest.raises(ValueError, match="repeats the field") as echoed:
        load_funding_sources({ENV_FUNDING_SOURCES: repeated_field})
    assert secret not in str(echoed.value)
    extra = _source()
    extra[secret] = "x"
    with pytest.raises(ValueError, match="extra") as echoed:
        load_funding_sources(_env(extra))
    assert secret not in str(echoed.value)
    missing = _source()
    del missing["byok"]
    with pytest.raises(ValueError, match="missing") as echoed:
        load_funding_sources(_env(missing))
    assert "byok" not in str(echoed.value)
    unset = _env(_source(name=secret))
    del unset["ATLAS_FUNDING_SUBS_A"]
    with pytest.raises(ValueError, match="unset") as echoed:
        load_funding_sources(unset)
    assert secret not in str(echoed.value)
    assert "ATLAS_FUNDING_SUBS_A" not in str(echoed.value)
    with pytest.raises(ValueError, match="repeats the key") as echoed:
        load_funding_sources(
            _env(_source(), _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_A"))
        )
    assert "ATLAS_FUNDING_SUBS_A" not in str(echoed.value)
    with pytest.raises(ValueError, match="tenant credential") as echoed:
        load_funding_sources(_env(_source(key_env="ATLAS_TENANT_MODEL_KEY")))
    assert "ATLAS_TENANT_MODEL_KEY" not in str(echoed.value)
    denied = _source(key_env="ATLAS_FUNDING_BYOK")
    with pytest.raises(ValueError, match="is not a key") as echoed:
        load_funding_sources(
            {
                ENV_FUNDING_SOURCES: json.dumps([denied]),
                "ATLAS_FUNDING_BYOK": "sk-or-v1-x",
            }
        )
    assert "ATLAS_FUNDING_BYOK" not in str(echoed.value)
    with pytest.raises(ValueError, match="pilot key") as echoed:
        load_funding_sources(_env(_source(key_env="ATLAS_OTHER_KEY")))
    assert "ATLAS_OTHER_KEY" not in str(echoed.value)
    with pytest.raises(ValueError, match="not an OpenRouter model id") as echoed:
        configured_model({ENV_MODEL: secret}, MODEL_ID)
    assert secret not in str(echoed.value)
    with pytest.raises(ValueError, match="not an OpenRouter model id") as echoed:
        sources_cover((), secret)
    assert secret not in str(echoed.value)
    slashed = "sk-or-v1-secret/secretsecret"
    with pytest.raises(ValueError, match="model filter matches") as echoed:
        sources_cover((), slashed)
    assert slashed not in str(echoed.value)


@pytest.mark.parametrize(
    "key_env",
    ("ATLAS_FUNDING_SOURCES", "ATLAS_FUNDING_SOURCE", "ATLAS_FUNDING_BYOK"),
)
def test_a_document_or_handoff_name_is_not_a_funding_key(key_env):
    """Each denylisted name is refused as a key variable. Kills dropping
    any one of them from the denylist, which would accept the document
    or a handoff flag as the source's key."""
    item = _source(key_env=key_env)
    env = {ENV_FUNDING_SOURCES: json.dumps([item])}
    if key_env != ENV_FUNDING_SOURCES:
        env[key_env] = "sk-or-v1-subs-a"
    with pytest.raises(ValueError, match="is not a key"):
        load_funding_sources(env)


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
    with pytest.raises(ValueError, match="model filter matches"):
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
    with pytest.raises(ServiceError, match="tenant credential"):
        config_from_env({**base, **_env(_source(key_env="ATLAS_TENANT_MODEL_KEY"))})
    built = config_from_env({**base, **_env(_source())})
    assert built.provider == "offline"
    with pytest.raises(ServiceError, match="model filter matches"):
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


def test_a_refusal_mark_does_not_wait_for_the_probe_in_front_of_it():
    """The key probe runs outside the selector lock. A refusal recorded
    while a probe is in flight returns at once, and that source is not
    the one the claim takes. Kills holding the lock across the HTTPS
    call."""
    import threading

    started = threading.Event()
    release = threading.Event()

    def probe(key: str) -> KeyStatus:
        started.set()
        release.wait()
        return _credit()

    env = _env(
        _source(),
        _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_B"),
    )
    selector = _selector(env, probe)
    chosen: list[str] = []

    def claim() -> None:
        selection = selector.choose()
        assert selection.choice is not None
        chosen.append(selection.choice.name)

    claim_thread = threading.Thread(target=claim)
    claim_thread.start()
    assert started.wait(timeout=30)
    marked = threading.Event()

    def mark() -> None:
        assert selector.mark_refused("subs-a") is True
        marked.set()

    mark_thread = threading.Thread(target=mark)
    mark_thread.start()
    # The probe is blocked in ``release.wait`` with no timeout of its
    # own. This wait only fails when the mark cannot take the lock,
    # which is the mutant that holds the lock across the probe.
    assert marked.wait(timeout=30)
    release.set()
    claim_thread.join(timeout=30)
    mark_thread.join(timeout=30)
    assert not claim_thread.is_alive()
    assert chosen == ["subs-b"]


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
    assert "subs-a: the key probe failed" in first.error
    assert "sk-or" not in first.error
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


def test_the_remembered_cause_is_the_first_refused_source_in_spend_order():
    """The D92 post names the source the registry tries first. Kills
    keeping the last source's cause instead."""
    env = _env(_source(), _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_B"))
    selector = _selector(env, lambda key: _credit())
    assert selector.mark_refused("subs-a", KEY_OUT_OF_CREDIT) is True
    assert selector.mark_refused("subs-b", KEY_AUTH_REFUSED) is False
    selection = selector.choose()
    assert selection.choice is None
    assert selection.refusal == KEY_OUT_OF_CREDIT


def test_one_walk_keeps_the_first_refusal_when_a_later_source_returns_401():
    """A dry source and then a 401, in one ``choose``, post the dry
    source's cause. Kills remembering the last refusal in the walk."""
    env = _env(_source(), _source(name="subs-b", key_env="ATLAS_FUNDING_SUBS_B"))

    def probe(key: str) -> KeyStatus:
        if key == "sk-or-v1-subs-a":
            return _credit(remaining="0")
        raise KeyRefusedError("OpenRouter HTTP 401", review_error=KEY_AUTH_REFUSED)

    selection = _selector(env, probe).choose()
    assert selection.choice is None
    assert selection.refusal == KEY_OUT_OF_CREDIT
    assert selection.error == ""


def test_a_blank_key_is_skipped_and_can_be_chosen_once_it_is_set():
    """A blank key is not probed and is not remembered as refused.
    Kills treating a missing value as out of credit."""
    env = _env(_source())
    calls: list[str] = []

    def probe(key: str) -> KeyStatus:
        calls.append(key)
        return _credit()

    selector = _selector(env, probe)
    env["ATLAS_FUNDING_SUBS_A"] = "   "
    first = selector.choose()
    assert first.choice is None
    assert first.refusal == ""
    assert "subs-a: the key is unset" in first.error
    assert calls == []
    env["ATLAS_FUNDING_SUBS_A"] = "sk-or-v1-subs-a"
    second = selector.choose()
    assert second.choice is not None
    assert second.choice.name == "subs-a"
    assert calls == ["sk-or-v1-subs-a"]


def test_an_unrecognized_probe_error_does_not_become_a_refusal():
    """A ``KeyRefusedError`` whose cause is not a D92 cause skips the
    source without remembering it. Kills posting that text as the
    review error."""
    env = _env(_source())
    calls = {"n": 0}

    def probe(key: str) -> KeyStatus:
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyRefusedError(
                "OpenRouter HTTP 403", review_error="provider flagged the input"
            )
        return _credit()

    selector = _selector(env, probe)
    first = selector.choose()
    assert first.choice is None
    assert first.refusal == ""
    assert "subs-a: the probe refused for a reason that is not a key refusal" in (
        first.error
    )
    assert "flagged" not in first.error
    second = selector.choose()
    assert second.choice is not None
    assert second.choice.name == "subs-a"


def test_a_probe_that_does_not_parse_fails_the_selection_without_crashing():
    """A 200 the key parser cannot read, including an unlimited key, is
    an error selection, not an exception out of ``choose``. Kills letting
    ``PricingUnknownError`` escape into the claim handler."""
    from atlas_reviewer.pricing import PricingUnknownError

    def probe(key: str) -> KeyStatus:
        raise PricingUnknownError("non-JSON response from the key endpoint")

    selection = _selector(_env(_source()), probe).choose()
    assert selection.choice is None
    assert selection.refusal == ""
    assert "subs-a: the key probe failed" in selection.error


def test_two_skips_keep_both_sources_and_both_reasons():
    """A probe failure and an over-ceiling key are different reasons.
    Kills collapsing every skip into one unattributed string."""
    env = _env(
        _source(),
        _source(name="high", key_env="ATLAS_FUNDING_HIGH", key_ceiling_usd="195"),
    )

    def probe(key: str) -> KeyStatus:
        if key == "sk-or-v1-subs-a":
            raise BoundaryError("OpenRouter HTTP 500")
        return _credit(limit="500")

    selection = _selector(env, probe).choose()
    assert "subs-a: the key probe failed" in selection.error
    assert "high: the key limit is over the source ceiling" in selection.error
    assert "sk-or" not in selection.error


def test_a_choice_repr_does_not_contain_the_key():
    """The dataclass repr is printable. The key value is not. Kills the
    default repr, which would include the credential."""
    choice = FundingChoice(
        "subs-a",
        "sk-or-v1-subs-a-secret",
        ("anthropic",),
        False,
        Decimal(195),
        True,
    )
    assert "sk-or-v1-subs-a-secret" not in repr(choice)
    assert "sk-or-v1-subs-a-secret" not in repr(FundingSelection(choice=choice))


def test_the_key_probe_classifies_401_and_402_and_never_echoes_the_body(monkeypatch):
    """The live probe's error is the status and the URL. The response
    body and the bearer token stay out of it. A 500 is a boundary
    error, not a key refusal. A 200 that is not a JSON object is not
    remaining credit. Kills classifying every non-200 as out of credit,
    putting the body on the error, and treating a malformed 200 as a
    key that still has credit."""
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
    from atlas_reviewer.pricing import PricingUnknownError

    seen["status"] = 200
    seen["payload"] = b"not json, and the body names sk-or-v1-probe-secret"
    with pytest.raises(PricingUnknownError) as unparsed:
        key_probe(secret)
    assert secret not in str(unparsed.value)
    assert "not json" not in str(unparsed.value)
    seen["payload"] = b"\xff\xfe"
    with pytest.raises(PricingUnknownError) as unreadable:
        key_probe(secret)
    assert secret not in str(unreadable.value)
    seen["payload"] = b"[1, 2]"
    with pytest.raises(PricingUnknownError) as array:
        key_probe(secret)
    assert secret not in str(array.value)
    seen["payload"] = b"null"
    with pytest.raises(PricingUnknownError) as null_body:
        key_probe(secret)
    assert secret not in str(null_body.value)
