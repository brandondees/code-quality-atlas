# SPDX-License-Identifier: MIT
"""OpenRouter adapter and the per-review budget: every limit is enforced in
code before a request is sent. No test here touches the network."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from atlas_reviewer import openrouter
from atlas_reviewer.budget import (
    BudgetRefusedError,
    CallLimits,
    ReviewBudget,
    input_token_bound,
    prompt_token_room,
    worst_case_usd,
)
from atlas_reviewer.http import HttpResponse
from atlas_reviewer.openrouter import (
    ENV_ALLOW_SAFETY_RETENTION,
    ENV_MODEL,
    ENV_PROVIDERS,
    ENV_REQUIRE_ZDR,
    MODEL_ID,
    PINNED_PROVIDERS,
    OpenRouterProvider,
    model_route,
)
from atlas_reviewer.ports import BoundaryError, ByokRefusedError
from atlas_reviewer.pricing import (
    PricingUnknownError,
    parse_key_status,
    parse_model_terms,
)
from atlas_reviewer.prompt import Prompt

KEY = "sk-or-v1-" + "f" * 64
API = "https://openrouter.ai/api/v1"
SMALL = Prompt("system", "review this")


def catalog(**pricing_changes):
    pricing = {
        "prompt": "0.000003",
        "completion": "0.000015",
        "request": "0",
        "input_cache_write": "0.00000375",
        "overrides": [{"prompt": "0.000006", "completion": "0.0000225"}],
        **pricing_changes,
    }
    return {
        "data": {
            "id": MODEL_ID,
            "context_length": 1_000_000,
            "pricing": {k: v for k, v in pricing.items() if v is not None},
            "top_provider": {"max_completion_tokens": 64_000},
        }
    }


_OMIT = object()


def key_status(limit=5, remaining=5, usage=0, include_byok_in_limit=True, **extra):
    data = {"limit": limit, "limit_remaining": remaining, "usage": usage, **extra}
    if include_byok_in_limit is not _OMIT:
        data["include_byok_in_limit"] = include_byok_in_limit
    return {"data": data}


def endpoint_price(**changes):
    """The fixture's selected-endpoint rates. They match the catalog's
    highest tier so older assertions keep their numbers, and a test that
    needs a different rate passes the change here, not on the catalog."""
    price = {
        "prompt": "0.000006",
        "completion": "0.0000225",
        "request": "0",
        "input_cache_write": "0.00000375",
    }
    price.update(changes)
    return {key: value for key, value in price.items() if value is not None}


def display_name(tag):
    """A human-readable provider name that is not the slug.

    Live rows carry both. `provider_name` is ``Amazon Bedrock`` where
    `tag` is ``amazon-bedrock``.
    """
    known = {
        "amazon-bedrock": "Amazon Bedrock",
        "google-vertex/europe": "Google",
        "google-vertex/global": "Google",
        "google-vertex/us": "Google",
        "fireworks": "Fireworks",
        "deepinfra/fp8": "DeepInfra",
        "deepinfra/fp4": "DeepInfra",
    }
    if tag in known:
        return known[tag]
    titled = tag.replace("-", " ").replace("/", " ").title()
    if titled == tag:
        return f"{tag} provider"
    return titled


def with_terms(row, **changes):
    """A hand-built endpoint row the selector can price."""
    filled = {
        "pricing": endpoint_price(),
        "context_length": 1_000_000,
        "max_completion_tokens": 64_000,
    }
    filled.update(row)
    filled.update(changes)
    tag = filled.get("tag")
    if isinstance(tag, str) and "provider_name" not in filled:
        filled["provider_name"] = display_name(tag)
    return filled


def zdr_payload(
    model=MODEL_ID,
    providers=PINNED_PROVIDERS,
    *,
    safety=False,
    parameters=None,
    pricing=None,
    context_length=1_000_000,
    max_completion_tokens=64_000,
):
    params = (
        ["reasoning", "include_reasoning", "max_tokens", "tools"]
        if parameters is None
        else list(parameters)
    )
    price = endpoint_price(**(pricing or {}))
    rows = [
        {
            "model_id": model,
            "tag": tag,
            "provider_name": display_name(tag),
            "safety_retention": safety,
            "supported_parameters": params,
            "pricing": price,
            "context_length": context_length,
            "max_completion_tokens": max_completion_tokens,
        }
        for tag in providers
    ]
    # A different model and a non-string tag are present and must be ignored.
    rows.append(
        {
            "model_id": "other/model",
            "tag": "other",
            "safety_retention": False,
            "supported_parameters": ["reasoning"],
        }
    )
    rows.append(
        {
            "model_id": model,
            "tag": None,
            "safety_retention": False,
            "supported_parameters": ["reasoning"],
        }
    )
    return {"data": rows}


def completion(text="review text", model=MODEL_ID, usage=None, finish="stop"):
    return {
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0123},
    }  # fmt: skip


def reply(payload, status=200, headers=None):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return HttpResponse(status, headers or {}, raw)


class OpenRouterFake:
    """Serves the key and catalog endpoints; chat replies come from a script."""

    def __init__(
        self, *chat, key=None, model=None, zdr=None, catalogs=None, endpoints=None
    ):
        self.chat = list(chat)
        self.key = key if key is not None else reply(key_status())
        self.model = model if model is not None else reply(catalog())
        self.catalogs = catalogs or {}
        self.zdr = zdr if zdr is not None else reply(zdr_payload())
        self.endpoints = endpoints
        self.requests = []

    def request(self, method, url, headers, body, timeout_s, max_bytes=None):
        self.requests.append((method, url, dict(headers), body))
        if url == f"{API}/key":
            return self.key
        if url == f"{API}/endpoints/zdr":
            return self.zdr
        models = f"{API}/models/"
        if url.startswith(models) and url.endswith("/endpoints"):
            if self.endpoints is None:
                model_id = url[len(models) : -len("/endpoints")]
                return reply({"data": {"id": model_id, "endpoints": []}})
            return self.endpoints
        if url.startswith(f"{API}/model/") and not url.startswith(models):
            model_id = url[len(f"{API}/model/") :]
            if model_id in self.catalogs:
                return self.catalogs[model_id]
            return self.model
        step = self.chat.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def chat_requests(self):
        return [r for r in self.requests if r[1].endswith("/chat/completions")]


def provider(fake, **limits):
    p = OpenRouterProvider(fake, KEY, limits=CallLimits(**limits) if limits else None)
    p.preflight()
    return p


# --- request shape ---------------------------------------------------------


def test_request_is_pinned_to_one_model_with_no_fallbacks_or_plugins():
    fake = OpenRouterFake(reply(completion()))
    assert provider(fake).complete(SMALL) == "review text"
    ((method, url, headers, body),) = fake.chat_requests()
    sent = json.loads(body)
    assert (method, url) == ("POST", f"{API}/chat/completions")
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert sent["model"] == MODEL_ID
    assert "models" not in sent and "plugins" not in sent and "tools" not in sent
    assert ":online" not in sent["model"]
    assert sent["max_tokens"] == 24_000
    assert sent["reasoning"] == {"max_tokens": 12_000, "exclude": True}
    assert sent["stream"] is False
    assert sent["provider"] == {
        "only": list(PINNED_PROVIDERS),
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
        "max_price": {"prompt": 6.0, "completion": 22.5},
    }
    assert "google-vertex" not in sent["provider"]["only"]


@pytest.mark.parametrize(
    "slugs",
    [
        (),
        ("",),
        ("Google-Vertex/us",),
        ("../amazon-bedrock",),
        ("amazon bedrock",),
    ],
)
def test_an_empty_or_malformed_provider_slug_is_refused_before_any_request(slugs):
    fake = OpenRouterFake(reply(completion()))
    with pytest.raises(
        BudgetRefusedError, match="allowlist is empty|not a provider slug"
    ):
        OpenRouterProvider(fake, KEY, providers=slugs)
    assert fake.requests == []


@pytest.mark.parametrize(
    "slugs",
    [
        ("google-vertex",),
        ("google-vertex/us-east5",),
        ("amazon-bedrock/eu-west-1",),
        ("openai",),
        ("not-a-provider",),
    ],
)
def test_a_slug_with_no_pure_zdr_endpoint_is_not_sent(slugs):
    fake = OpenRouterFake(reply(completion()))
    adapter = OpenRouterProvider(fake, KEY, providers=slugs)
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="no eligible zero-data-retention"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []
    assert any(url.endswith("/endpoints/zdr") for _m, url, _h, _b in fake.requests)


def test_catalog_is_fetched_without_the_key():
    fake = OpenRouterFake(reply(completion()))
    provider(fake).complete(SMALL)
    catalog_get = next(r for r in fake.requests if "/model/" in r[1])
    zdr_get = next(r for r in fake.requests if r[1].endswith("/endpoints/zdr"))
    assert "Authorization" not in catalog_get[2]
    assert "Authorization" not in zdr_get[2]


def test_one_provider_is_a_valid_pin_and_the_output_cap_stays_configured():
    fake = OpenRouterFake(reply(completion()))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    assert adapter.complete(SMALL) == "review text"
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["provider"]["only"] == ["amazon-bedrock"]
    assert sent["provider"]["zdr"] is True
    assert sent["provider"]["data_collection"] == "deny"
    assert sent["provider"]["allow_fallbacks"] is False
    assert sent["provider"]["require_parameters"] is True
    # The catalog fixture's completion limit is 64_000. The request uses
    # the configured cap, not that catalog number.
    assert sent["max_tokens"] == 24_000
    assert sent["reasoning"] == {"max_tokens": 12_000, "exclude": True}
    assert sent["cache_control"] == {"type": "ephemeral"}


def test_an_anthropic_route_sends_cache_control_even_when_no_endpoint_lists_it():
    """OpenRouter never lists cache_control. ZDR Bedrock still honors it."""
    listed = zdr_payload(
        providers=("amazon-bedrock",), parameters=["reasoning", "max_tokens"]
    )
    assert all(
        "cache_control" not in row["supported_parameters"]
        for row in listed["data"]
        if row.get("tag")
    )
    fake = OpenRouterFake(reply(completion()), zdr=reply(listed))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    adapter.complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["model"] == MODEL_ID
    assert sent["provider"]["zdr"] is True
    assert sent["provider"]["require_parameters"] is True
    assert sent["cache_control"] == {"type": "ephemeral"}
    assert "cache_control: true" in adapter.usage_lines()[0]

    other = "z-ai/glm-5.3"
    catalog_row = catalog()
    catalog_row["data"]["id"] = other
    quiet = zdr_payload(other, ("fireworks",), parameters=["reasoning", "max_tokens"])
    bare = OpenRouterFake(
        reply(completion(model=other)),
        model=reply(catalog_row),
        zdr=reply(quiet),
    )
    glm = OpenRouterProvider(bare, KEY, model_id=other, providers=("fireworks",))
    glm.preflight()
    glm.complete(SMALL)
    body = json.loads(bare.chat_requests()[0][3])
    assert "cache_control" not in body
    assert "cache_control: false" in glm.usage_lines()[0]


def test_reasoning_follows_the_endpoint_parameters():
    both = zdr_payload(parameters=["reasoning", "max_tokens"])
    fake = OpenRouterFake(reply(completion()), zdr=reply(both))
    adapter = provider(fake)
    adapter.complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["reasoning"]["max_tokens"] == 12_000
    assert sent["cache_control"] == {"type": "ephemeral"}
    assert sent["provider"]["require_parameters"] is True

    no_reasoning = zdr_payload(parameters=["max_tokens", "tools"])
    bare = OpenRouterFake(reply(completion()), zdr=reply(no_reasoning))
    provider(bare).complete(SMALL)
    omitted = json.loads(bare.chat_requests()[0][3])
    assert "reasoning" not in omitted
    assert omitted["cache_control"] == {"type": "ephemeral"}
    assert omitted["max_tokens"] == 24_000

    mixed = {
        "data": [
            with_terms(
                {
                    "model_id": MODEL_ID,
                    "tag": "amazon-bedrock",
                    "safety_retention": False,
                    "supported_parameters": ["reasoning"],
                }
            ),
            with_terms(
                {
                    "model_id": MODEL_ID,
                    "tag": "google-vertex/global",
                    "safety_retention": False,
                    "supported_parameters": ["max_tokens"],
                }
            ),
        ]
    }
    half = OpenRouterFake(reply(completion()), zdr=reply(mixed))
    pinned = OpenRouterProvider(
        half, KEY, providers=("amazon-bedrock", "google-vertex/global")
    )
    pinned.preflight()
    pinned.complete(SMALL)
    body = json.loads(half.chat_requests()[0][3])
    assert "reasoning" not in body
    assert body["cache_control"] == {"type": "ephemeral"}


def test_safety_retention_is_off_unless_the_route_opts_in():
    retained = zdr_payload(providers=("google-vertex/global",), safety=True)
    fake = OpenRouterFake(reply(completion()), zdr=reply(retained))
    adapter = OpenRouterProvider(fake, KEY, providers=("google-vertex/global",))
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="Safety Retention"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []

    allowed = OpenRouterProvider(
        fake, KEY, providers=("google-vertex/global",), allow_safety_retention=True
    )
    allowed.preflight()
    assert allowed.complete(SMALL) == "review text"
    assert json.loads(fake.chat_requests()[0][3])["provider"]["zdr"] is True


def test_a_mixed_safety_row_blocks_the_slug_until_the_opt_in():
    mixed = {
        "data": [
            {
                "model_id": MODEL_ID,
                "tag": "google-vertex/global",
                "safety_retention": False,
                "supported_parameters": ["reasoning"],
            },
            {
                "model_id": MODEL_ID,
                "tag": "google-vertex/global",
                "safety_retention": True,
                "supported_parameters": ["reasoning"],
            },
        ]
    }
    fake = OpenRouterFake(reply(completion()), zdr=reply(mixed))
    adapter = OpenRouterProvider(fake, KEY, providers=("google-vertex/global",))
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="Safety Retention"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []


def test_a_response_is_accepted_only_from_the_configured_model():
    alt = "deepseek/deepseek-v4.1-flash"
    listed = catalog()
    listed["data"]["id"] = alt
    fake = OpenRouterFake(
        reply(completion(model=MODEL_ID)),
        catalogs={alt: reply(listed)},
        zdr=reply(zdr_payload(alt, ("deepinfra/fp8",), parameters=["max_tokens"])),
    )
    adapter = OpenRouterProvider(fake, KEY, model_id=alt, providers=("deepinfra/fp8",))
    adapter.preflight()
    with pytest.raises(BoundaryError, match=re.escape(MODEL_ID)):
        adapter.complete(SMALL)
    assert json.loads(fake.chat_requests()[0][3])["model"] == alt

    dated = OpenRouterFake(
        reply(completion(model=f"{alt}-20261017")),
        catalogs={alt: reply(listed)},
        zdr=reply(zdr_payload(alt, ("deepinfra/fp8",), parameters=["max_tokens"])),
    )
    ok = OpenRouterProvider(dated, KEY, model_id=alt, providers=("deepinfra/fp8",))
    ok.preflight()
    assert ok.complete(SMALL) == "review text"

    other = OpenRouterFake(
        reply(completion(model=f"{alt}-turbo")),
        catalogs={alt: reply(listed)},
        zdr=reply(zdr_payload(alt, ("deepinfra/fp8",), parameters=["max_tokens"])),
    )
    rejected = OpenRouterProvider(
        other, KEY, model_id=alt, providers=("deepinfra/fp8",)
    )
    rejected.preflight()
    with pytest.raises(BoundaryError, match="turbo"):
        rejected.complete(SMALL)


def test_the_route_reads_the_flag_before_the_environment():
    route = model_route({})
    assert route.model_id == MODEL_ID
    assert route.providers == PINNED_PROVIDERS
    assert route.allow_safety_retention is False
    assert route.require_zdr is True

    chosen = model_route(
        {
            ENV_MODEL: "deepseek/deepseek-v4.1-flash",
            ENV_PROVIDERS: "fireworks, fireworks",
            ENV_ALLOW_SAFETY_RETENTION: "true",
        },
        model="google/gemini-3.5-flash",
        providers="deepinfra/fp8",
        allow_safety_retention=False,
    )
    # The flag names the model and the provider. The env can still turn
    # Safety Retention on, because the flag's store_true cannot say "off".
    assert chosen.model_id == "google/gemini-3.5-flash"
    assert chosen.providers == ("deepinfra/fp8",)
    assert chosen.allow_safety_retention is True
    assert chosen.require_zdr is True
    assert model_route({ENV_REQUIRE_ZDR: "false"}).require_zdr is False
    assert (
        model_route({ENV_REQUIRE_ZDR: "true"}, require_zdr=False).require_zdr is False
    )

    with pytest.raises(BudgetRefusedError, match="not an OpenRouter model id"):
        model_route({}, model="anthropic/claude-sonnet-5.5:online")
    with pytest.raises(BudgetRefusedError, match="empty"):
        model_route({}, model="")
    with pytest.raises(BudgetRefusedError, match="must be true or false"):
        model_route({ENV_ALLOW_SAFETY_RETENTION: "yes"})
    # An empty variable is unset, so the default model stands.
    assert model_route({ENV_MODEL: "  "}).model_id == MODEL_ID
    assert (
        model_route({ENV_ALLOW_SAFETY_RETENTION: "FALSE"}).allow_safety_retention
        is False
    )
    with pytest.raises(BudgetRefusedError, match="empty slug"):
        model_route({}, providers="amazon-bedrock,,google-vertex/us")
    with pytest.raises(BudgetRefusedError, match="allowlist is empty"):
        model_route({}, providers="  ")
    with pytest.raises(BudgetRefusedError, match="must be a boolean"):
        model_route({}, allow_safety_retention="true")  # type: ignore[arg-type]


def test_an_unreadable_zdr_list_refuses_before_a_completion():
    fake = OpenRouterFake(reply(completion()), zdr=reply({"data": "nope"}))
    adapter = provider(fake)
    with pytest.raises(PricingUnknownError, match="no data array"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []

    broken = OpenRouterFake(
        reply(completion()),
        zdr=reply({"data": [{"model_id": MODEL_ID, "tag": "amazon-bedrock"}]}),
    )
    # The other three default slugs have no row, so the refusal names them.
    # The bedrock row has no boolean and is refused on its own if it is the
    # only slug. Pin that one slug so the missing flag is the reason.
    only = OpenRouterProvider(broken, KEY, providers=("amazon-bedrock",))
    only.preflight()
    with pytest.raises(BudgetRefusedError, match="not a boolean"):
        only.complete(SMALL)
    assert broken.chat_requests() == []

    foreign = OpenRouterFake(reply(completion()), zdr=reply({"data": ["row"]}))
    refused = provider(foreign)
    with pytest.raises(PricingUnknownError, match="non-object"):
        refused.complete(SMALL)
    assert foreign.chat_requests() == []

    messy = zdr_payload(providers=("amazon-bedrock",), parameters=["reasoning"])
    messy["data"][0]["supported_parameters"] = {"reasoning": True}
    quiet = OpenRouterFake(reply(completion()), zdr=reply(messy))
    pinned = OpenRouterProvider(quiet, KEY, providers=("amazon-bedrock",))
    pinned.preflight()
    pinned.complete(SMALL)
    assert "reasoning" not in json.loads(quiet.chat_requests()[0][3])


def test_a_non_200_zdr_list_and_a_timeout_send_no_completion():
    refused = OpenRouterFake(reply(completion()), zdr=reply({}, status=503))
    adapter = provider(refused)
    with pytest.raises(PricingUnknownError, match="HTTP 503"):
        adapter.complete(SMALL)
    assert refused.chat_requests() == []
    assert any(url.endswith("/endpoints/zdr") for _m, url, _h, _b in refused.requests)

    class Timeout(OpenRouterFake):
        def request(self, method, url, headers, body, timeout_s, max_bytes=None):
            if str(url).endswith("/endpoints/zdr"):
                self.requests.append((method, url, dict(headers), body))
                raise BoundaryError("timed out")
            return super().request(method, url, headers, body, timeout_s, max_bytes)

    timed = Timeout(reply(completion()))
    waiting = provider(timed)
    with pytest.raises(BoundaryError, match="timed out"):
        waiting.complete(SMALL)
    assert timed.chat_requests() == []


def test_max_tokens_is_sent_when_the_endpoint_does_not_advertise_it():
    fake = OpenRouterFake(
        reply(completion()), zdr=reply(zdr_payload(parameters=["tools"]))
    )
    provider(fake).complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["max_tokens"] == 24_000
    assert "max_tokens" not in sent.get("provider", {})


def test_a_safety_retention_child_refuses_the_parent_slug():
    payload = zdr_payload(providers=("amazon-bedrock",))
    payload["data"].append(
        {
            "model_id": MODEL_ID,
            "tag": "amazon-bedrock/eu-west-1",
            "safety_retention": True,
            "supported_parameters": ["reasoning", "max_tokens"],
        }
    )
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="child tag"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []


def test_a_bare_slug_with_only_child_rows_names_those_tags_and_sends_nothing():
    payload = zdr_payload(providers=("deepinfra/fp8",), parameters=["tools"])
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("deepinfra",))
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="deepinfra/fp8"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []


def test_a_tag_sharing_only_the_prefix_does_not_refuse_the_parent():
    payload = zdr_payload(providers=("amazon-bedrock",))
    payload["data"].append(
        {
            "model_id": MODEL_ID,
            "tag": "amazon-bedrock-extra",
            "safety_retention": True,
            "supported_parameters": ["reasoning", "max_tokens"],
        }
    )
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    assert adapter.complete(SMALL) == "review text"
    assert json.loads(fake.chat_requests()[0][3])["provider"]["only"] == [
        "amazon-bedrock"
    ]


def test_a_pure_child_does_not_rewrite_the_requested_slug():
    payload = zdr_payload(providers=("amazon-bedrock",))
    payload["data"].append(
        with_terms(
            {
                "model_id": MODEL_ID,
                "tag": "amazon-bedrock/us-east-1",
                "safety_retention": False,
                "supported_parameters": ["reasoning", "max_tokens", "tools"],
            }
        )
    )
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    assert adapter.complete(SMALL) == "review text"
    assert json.loads(fake.chat_requests()[0][3])["provider"]["only"] == [
        "amazon-bedrock"
    ]


def test_the_catalog_is_documented_as_fetched_once_per_review():
    doc = openrouter.__doc__ or ""
    assert "fetched once per provider for the review" in doc
    assert "re-fetched" not in doc
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert "fetched once per provider for the review and reused" in readme
    assert "fetched once per turn" not in readme


def test_the_zdr_list_is_read_once_for_the_provider():
    fake = OpenRouterFake(reply(completion()), reply(completion()))
    adapter = provider(fake)
    adapter.complete(SMALL)
    adapter.complete(SMALL)
    zdr_reads = [
        url for _m, url, _h, _b in fake.requests if url.endswith("/endpoints/zdr")
    ]
    assert zdr_reads == [f"{API}/endpoints/zdr"]


def test_a_zero_catalog_rate_and_a_non_finite_price_send_no_completion():
    zero = catalog(prompt="0", completion="0", overrides=[])
    fake = OpenRouterFake(reply(completion()), model=reply(zero))
    adapter = provider(fake)
    with pytest.raises(PricingUnknownError, match="pricing.prompt is zero"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []

    huge = zdr_payload(providers=("amazon-bedrock",), pricing={"prompt": "1e1000"})
    overflow = OpenRouterFake(reply(completion()), zdr=reply(huge))
    priced = OpenRouterProvider(overflow, KEY, providers=("amazon-bedrock",))
    priced.preflight()
    with pytest.raises(PricingUnknownError, match="not a finite"):
        priced.complete(SMALL)
    assert overflow.chat_requests() == []


def test_the_environment_selects_the_model_and_provider_without_a_flag():
    route = model_route(
        {
            ENV_MODEL: "deepseek/deepseek-v4.1-flash",
            ENV_PROVIDERS: "fireworks",
        }
    )
    assert route.model_id == "deepseek/deepseek-v4.1-flash"
    assert route.providers == ("fireworks",)
    assert route.allow_safety_retention is False


# --- 3-call cap, retries included ------------------------------------------


def test_retries_count_against_the_three_call_cap():
    fake = OpenRouterFake(*[reply({}, status=503) for _ in range(5)])
    p = provider(fake)
    with pytest.raises(BoundaryError, match="HTTP 503"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 3
    report = p.usage_lines()
    assert report[-1].endswith("3 of 3 calls used")


def test_cap_spans_every_completion_in_the_review():
    fake = OpenRouterFake(
        reply({}, status=429), reply(completion()), reply(completion())
    )
    p = provider(fake)
    assert p.complete(SMALL) == "review text"
    assert p.complete(SMALL) == "review text"
    with pytest.raises(BudgetRefusedError, match="call cap reached: 3 model calls"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 3


def test_a_numeric_retry_after_is_honoured_and_capped():
    sleeps = []
    fake = OpenRouterFake(
        reply({}, status=503, headers={"Retry-After": "1"}),
        reply({}, status=429, headers={"Retry-After": "120"}),
        reply(completion()),
    )
    p = OpenRouterProvider(fake, KEY, sleep=sleeps.append)
    p.preflight()
    assert p.complete(SMALL) == "review text"
    assert sleeps == [1.0, 8.0]
    assert len(fake.chat_requests()) == 3


def test_a_non_numeric_retry_after_falls_back_to_backoff():
    sleeps = []
    fake = OpenRouterFake(
        reply({}, status=503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
        reply({}, status=429, headers={"Retry-After": "-5"}),
        reply(completion()),
    )
    p = OpenRouterProvider(fake, KEY, sleep=sleeps.append)
    p.preflight()
    assert p.complete(SMALL) == "review text"
    assert sleeps == [2.0, 4.0]


def test_transport_errors_are_retried_within_the_cap():
    sleeps = []
    fake = OpenRouterFake(BoundaryError("timed out"), reply(completion()))
    p = OpenRouterProvider(fake, KEY, sleep=sleeps.append)
    p.preflight()
    assert p.complete(SMALL) == "review text"
    assert sleeps == [2.0]
    assert "transport error: timed out" in p.usage_lines()[1]


def test_non_retryable_errors_stop_at_once():
    fake = OpenRouterFake(reply({}, status=400), reply(completion()))
    with pytest.raises(BoundaryError, match="HTTP 400"):
        provider(fake).complete(SMALL)
    assert len(fake.chat_requests()) == 1


# --- $3 reservation ----------------------------------------------------------


def test_call_whose_worst_case_could_pass_three_dollars_is_refused():
    big = Prompt("s", "x" * 170_000)
    terms = parse_model_terms(catalog(), MODEL_ID)
    worst = worst_case_usd(
        input_token_bound(big.system + big.user), terms, CallLimits()
    )
    assert Decimal("1.5") < worst < Decimal(3)
    fake = OpenRouterFake(reply({}, status=503), reply(completion()))
    p = provider(fake)
    with pytest.raises(BoundaryError, match="HTTP 503"):
        p.complete(big)
    assert len(fake.chat_requests()) == 1
    assert any(
        line.startswith("refused: cost cap") and "over $3.00" in line
        for line in p.usage_lines()
    )


def test_a_separate_reasoning_price_reserves_the_whole_output_cap():
    """The hint is not a bound. A separate reasoning rate is reserved on
    every output token, not only on `reasoning_max_tokens`."""
    terms = parse_model_terms(catalog(internal_reasoning="0.00002"), MODEL_ID)
    plain = parse_model_terms(catalog(), MODEL_ID)
    limits = CallLimits()
    extra = limits.max_output_tokens * terms.reasoning_rate
    assert extra == Decimal("0.48")
    assert (
        worst_case_usd(1000, terms, limits)
        == worst_case_usd(1000, plain, limits) + extra
    )
    hinted = CallLimits(reasoning_max_tokens=100)
    assert worst_case_usd(1000, terms, hinted) == worst_case_usd(1000, terms, limits)


def test_reported_reasoning_past_the_hint_stays_inside_the_reservation():
    """A reply can report more reasoning tokens than the hint. The fallback
    price of that reply, the path `_actual_cost` uses when `usage.cost` is
    missing, must not exceed the reservation that was held for the call."""
    terms = parse_model_terms(catalog(internal_reasoning="0.00002"), MODEL_ID)
    assert terms.reasoning_rate == Decimal("0.00002")
    limits = CallLimits()
    # The whole output cap, not the hint plus a little. Pricing only the
    # hint would leave this reply over the reservation.
    reasoning = limits.max_output_tokens
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": reasoning,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
        "is_byok": False,
    }
    fake = OpenRouterFake(
        reply(completion(usage=usage)),
        model=reply(catalog(internal_reasoning="0.00002")),
    )
    p = provider(fake, max_calls=1)
    p.preflight()
    p.complete(SMALL)
    record = p.budget.calls[0]
    assert record.actual_usd is not None
    assert record.actual_usd <= record.reserved_usd
    assert f"reasoning={reasoning}" in record.usage


def test_reservation_uses_the_highest_price_tier_and_cache_writes():
    terms = parse_model_terms(catalog(input_cache_write="0.00001"), MODEL_ID)
    assert terms.input_rate == Decimal("0.00001")
    assert terms.prompt_rate == Decimal("0.000006")
    assert terms.completion_rate == Decimal("0.0000225")
    worst = worst_case_usd(1000, terms, CallLimits())
    assert worst == Decimal("0.01") + Decimal("0.54")


def test_failed_attempts_stay_counted_at_their_full_reservation():
    budget = ReviewBudget(CallLimits())
    record = budget.reserve(Decimal("1.40"))
    budget.settle(record, "HTTP 503 (retryable)")
    budget.reserve(Decimal("1.40"))
    with pytest.raises(BudgetRefusedError, match="over \\$3.00"):
        budget.reserve(Decimal("0.21"))
    budget.reserve(Decimal("0.20"))
    assert budget.committed_usd() == Decimal("3.00")


def test_settled_actuals_replace_reservations():
    budget = ReviewBudget(CallLimits())
    record = budget.reserve(Decimal("2.90"))
    budget.settle(record, "ok", Decimal("0.10"))
    budget.reserve(Decimal("2.90"))
    assert budget.committed_usd() == Decimal("3.00")


def test_key_remaining_credit_caps_retries_too():
    fake = OpenRouterFake(
        reply({}, status=503),
        reply(completion()),
        key=reply(key_status(remaining=0.60)),
    )
    p = provider(fake)
    with pytest.raises(BoundaryError, match="HTTP 503"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    assert any("over $0.60" in line for line in p.usage_lines())


def test_worst_case_over_the_key_remaining_credit_is_never_sent():
    fake = OpenRouterFake(reply(completion()), key=reply(key_status(remaining=0.10)))
    with pytest.raises(BudgetRefusedError, match="over \\$0.10"):
        provider(fake).complete(SMALL)
    assert fake.chat_requests() == []


# --- token bounds --------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,zdr_kwargs,match",
    [
        (Prompt("s", "x" * 200_001), {}, "input cap"),
        (SMALL, {"max_completion_tokens": 8000}, "completion limit"),
        (SMALL, {"context_length": 20_000}, "context"),
    ],
)
def test_token_bounds_are_checked_before_sending(prompt, zdr_kwargs, match):
    fake = OpenRouterFake(reply(completion()), zdr=reply(zdr_payload(**zdr_kwargs)))
    with pytest.raises(BudgetRefusedError, match=match):
        provider(fake).complete(prompt)
    assert fake.chat_requests() == []


def test_prompt_token_room_is_what_still_fits_in_the_context():
    """The room a later step sizes a diff part against. The input cap wins
    when it is the tighter of the two bounds."""
    assert prompt_token_room(CallLimits()) == 176_000
    assert prompt_token_room(CallLimits(), context_tokens=100_000) == 76_000
    tight = CallLimits(
        max_input_tokens=50_000, max_output_tokens=30_000, reasoning_max_tokens=1_000
    )
    assert prompt_token_room(tight) == 50_000


def test_limits_reject_nonsense():
    for bad in (
        {"max_calls": 0},
        {"max_calls": 4},
        {"budget_usd": Decimal(0)},
        {"budget_usd": Decimal("3.01")},
        {"max_output_tokens": 100},
    ):
        with pytest.raises(ValueError):
            CallLimits(**bad)


# --- fail closed on unknown pricing -----------------------------------------


@pytest.mark.parametrize(
    "model,match",
    [
        (reply({}, status=404), "HTTP 404"),
        (reply(b"<html>"), "non-JSON"),
        (reply(b'{"a": "\xff"}'), "non-JSON"),
        (reply([]), "non-object"),
        (reply({"data": "x"}), "no data object"),
        (reply(catalog(prompt="-1")), "unknown"),
        (reply(catalog(prompt=None)), "pricing.prompt is missing"),
        (reply(catalog(completion="free")), "not a number"),
        (reply(catalog(completion=True)), "not a number"),
        (reply(catalog(completion="NaN")), "non-finite"),
        (reply(catalog(overrides={"prompt": "1"})), "overrides"),
        (reply(catalog(overrides=[{"completion": "-1"}])), "unknown"),
        (
            reply({"data": {**catalog()["data"], "id": "anthropic/other"}}),
            "not 'anthropic",
        ),
        (reply({"data": {**catalog()["data"], "pricing": None}}), "no pricing object"),
        (
            reply({"data": {**catalog()["data"], "context_length": None}}),
            "context_length",
        ),
        (
            reply({"data": {**catalog()["data"], "top_provider": None}}),
            "max_completion_tokens",
        ),
    ],
)
def test_unknown_or_unparseable_pricing_refuses_before_any_call(model, match):
    fake = OpenRouterFake(reply(completion()), model=model)
    with pytest.raises(PricingUnknownError, match=match):
        provider(fake).complete(SMALL)
    assert fake.chat_requests() == []


# --- key-limit preflight -------------------------------------------------------


@pytest.mark.parametrize(
    "key,match",
    [
        (reply(key_status(limit=None)), "no credit limit"),
        (reply(key_status(limit=5.01)), "over the \\$5.00 pilot ceiling"),
        (reply(key_status(limit=100, remaining=100)), "pilot ceiling"),
        (reply(key_status(remaining=0)), "no credit remaining"),
        (reply(key_status(remaining=None)), "limit_remaining"),
        (reply({}, status=401), "HTTP 401"),
        (reply(b"nope"), "non-JSON"),
        (reply({"data": None}), "no data object"),
    ],
)
def test_preflight_refuses_unless_the_key_has_a_hard_limit_of_at_most_five_dollars(
    key, match
):
    fake = OpenRouterFake(key=key)
    with pytest.raises(PricingUnknownError, match=match):
        OpenRouterProvider(fake, KEY).preflight()
    assert [r[1] for r in fake.requests] == [f"{API}/key"]
    assert fake.requests[0][2]["Authorization"] == f"Bearer {KEY}"


def test_a_raised_ceiling_accepts_that_key_and_names_the_setting_past_it():
    accepted = OpenRouterProvider(
        OpenRouterFake(key=reply(key_status(limit=25))),
        KEY,
        key_ceiling=Decimal(25),
    ).preflight()
    assert accepted.limit == Decimal(25)
    with pytest.raises(PricingUnknownError, match=r"\$25.01 is over the \$25") as exc:
        OpenRouterProvider(
            OpenRouterFake(key=reply(key_status(limit=25.01))),
            KEY,
            key_ceiling=Decimal(25),
        ).preflight()
    text = str(exc.value)
    assert "--key-ceiling-usd" in text
    assert "ATLAS_KEY_CEILING_USD" in text


def test_preflight_accepts_a_five_dollar_key():
    status = OpenRouterProvider(OpenRouterFake(), KEY).preflight()
    assert status == parse_key_status(key_status())
    assert status.counts_byok is True


@pytest.mark.parametrize("flag", [False, None, _OMIT], ids=["false", "null", "absent"])
def test_preflight_accepts_a_key_that_does_not_count_byok_spend(flag):
    """A website key leaves `include_byok_in_limit` false or absent. The
    other refusals (no limit, over $5, no credit left) still apply."""
    fake = OpenRouterFake(key=reply(key_status(include_byok_in_limit=flag)))
    status = OpenRouterProvider(fake, KEY).preflight()
    assert status.counts_byok is False
    assert status.limit == Decimal(5)
    assert [r[1] for r in fake.requests] == [f"{API}/key"]


def test_key_status_is_read_only_by_the_preflight_so_a_lagging_counter_cannot_mismatch():
    fake = OpenRouterFake(reply(completion()))
    p = provider(fake)
    p.complete(SMALL)
    key_reads = [r for r in fake.requests if r[1] == f"{API}/key"]
    assert len(key_reads) == 1
    assert fake.requests.index(key_reads[0]) == 0


def test_recorded_spend_comes_from_the_response_even_when_the_key_counter_reads_zero():
    zero_usage_key = reply(key_status(usage=0))
    fake = OpenRouterFake(
        reply(
            completion(usage={"prompt_tokens": 5, "completion_tokens": 5, "cost": 0.17})
        ),
        key=zero_usage_key,
    )
    p = provider(fake)
    p.complete(SMALL)
    assert any("$0.1700" in line for line in p.usage_lines())


def test_no_inference_without_a_passed_preflight():
    fake = OpenRouterFake(reply(completion()))
    with pytest.raises(BudgetRefusedError, match="preflight has not passed"):
        OpenRouterProvider(fake, KEY).complete(SMALL)
    assert fake.requests == []


# --- responses -----------------------------------------------------------------


def test_byok_upstream_cost_counts_toward_the_review_ceiling():
    """usage.cost on a BYOK call is OpenRouter's fee. The upstream charge
    is what the $3 ceiling has to see."""
    usage = {
        "prompt_tokens": 150_000,
        "completion_tokens": 100,
        "cost": "0.05",
        "is_byok": True,
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    fake = OpenRouterFake(
        *[reply(completion(usage=usage)) for _ in range(3)],
        key=reply(key_status(include_byok_in_limit=True)),
    )
    p = provider(fake)
    assert p.complete(SMALL) == "review text"
    assert p.complete(SMALL) == "review text"
    with pytest.raises(BudgetRefusedError, match="over \\$3.00"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 2
    assert p.budget.committed_usd() == Decimal("2.62")


def test_a_byok_call_without_an_upstream_cost_keeps_its_reservation():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": True,
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]
    assert "BYOK upstream cost not reported" in p.usage_lines()[1]


def test_an_unreadable_upstream_cost_keeps_the_reservation():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "cost_details": {"upstream_inference_cost": "nope"},
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]


def test_an_accepted_call_with_no_upstream_field_settles_usage_cost():
    """A missing upstream field keeps the reservation only when is_byok
    is true. An accepted call that omits the field settles usage.cost."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": "0.05"}
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd == Decimal("0.05")


def _no_byok_provider(usage, *, flag=False):
    fake = OpenRouterFake(
        reply(completion(usage=usage)),
        reply(completion()),
        key=reply(key_status(include_byok_in_limit=flag)),
    )
    return provider(fake), fake


def test_a_byok_response_keeps_its_upstream_cost_when_no_byok_mode_refuses_it():
    """The review stops. The call is still settled: a reported upstream
    charge counts, so the cap does not forget the spend."""
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": True,
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    p, fake = _no_byok_provider(usage)
    with pytest.raises(ByokRefusedError, match="usage.is_byok is true"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    assert fake.chat  # the next reply was not consumed
    assert p.budget.committed_usd() == Decimal("1.31")


@pytest.mark.parametrize("flag", [None, "false", 0, []])
def test_a_non_boolean_is_byok_is_refused_and_keeps_the_reservation(flag):
    """Only boolean false is non-BYOK. Null, a string, a number, or a list
    is not that value, so the review stops and the reservation stands."""
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": flag,
    }
    p, fake = _no_byok_provider(usage)
    with pytest.raises(ByokRefusedError, match="is not false"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    assert fake.chat  # the next reply was not consumed
    assert p.budget.calls[0].actual_usd is None
    assert "counted at the reservation" in p.usage_lines()[1]


def test_a_missing_is_byok_field_is_refused_and_keeps_the_reservation():
    """Fail closed. The usage cookbook's Chat Completions example omits
    `is_byok`, so absence is not proof the call was non-BYOK. With no
    upstream charge to read, the full reservation stays counted."""
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": "0.05"}
    p, fake = _no_byok_provider(usage)
    with pytest.raises(ByokRefusedError, match="no is_byok field"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    assert p.budget.calls[0].actual_usd is None
    assert "counted at the reservation" in p.usage_lines()[1]


def test_an_explicit_non_byok_response_is_accepted_when_the_flag_is_off():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": False,
    }
    p, fake = _no_byok_provider(usage)
    assert p.complete(SMALL) == "review text"
    assert len(fake.chat_requests()) == 1
    assert p.budget.committed_usd() == Decimal("0.05")


def _non_byok_usage(upstream):
    return {
        "prompt_tokens": 36_614,
        "completion_tokens": 576,
        "cost": "0.0790",
        "is_byok": False,
        "cost_details": {"upstream_inference_cost": upstream},
    }


@pytest.mark.parametrize("upstream", ["0.0790", "0.0120"])
def test_a_non_byok_call_settles_usage_cost_when_upstream_is_not_larger(upstream):
    """PR #585 settled twice the key charge by adding this field. An
    upstream amount equal to usage.cost (the live case) or below it is not
    added, and the budget line names the raw value."""
    p = provider(OpenRouterFake(reply(completion(usage=_non_byok_usage(upstream)))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd == Decimal("0.0790")
    assert (
        f"(upstream {upstream!r} reported, not added: is_byok false)"
        in p.usage_lines()[1]
    )


@pytest.mark.parametrize("upstream", ["0.0791", "0.1580", "1.26"])
def test_a_non_byok_call_settles_the_larger_upstream_cost(upstream):
    """If the upstream amount exceeds usage.cost the response is ambiguous,
    so the call is settled at the larger figure and never below it."""
    p = provider(OpenRouterFake(reply(completion(usage=_non_byok_usage(upstream)))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd == Decimal(upstream)
    assert (
        f"(upstream {upstream!r} exceeds usage.cost {Decimal('0.0790')}:"
        " settled at upstream)" in p.usage_lines()[1]
    )


def test_a_non_byok_call_with_a_null_upstream_settles_usage_cost():
    p = provider(OpenRouterFake(reply(completion(usage=_non_byok_usage(None)))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd == Decimal("0.0790")
    assert "(upstream None reported, not added" in p.usage_lines()[1]


@pytest.mark.parametrize("upstream", ["not-a-number", "-1", -1, {}, [], True])
def test_a_non_byok_call_with_an_unreadable_upstream_keeps_the_reservation(upstream):
    """A present, non-null upstream value that cannot be read is ambiguous,
    so the full reservation stays counted, as it does for any other flag."""
    p = provider(OpenRouterFake(reply(completion(usage=_non_byok_usage(upstream)))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd is None
    assert "counted at the reservation" in p.usage_lines()[1]
    assert f"(upstream {upstream!r} unreadable)" in p.usage_lines()[1]


def test_a_long_unreadable_upstream_value_is_cut_in_the_settlement_line():
    raw = "x" * 1000
    p = provider(OpenRouterFake(reply(completion(usage=_non_byok_usage(raw)))))
    p.complete(SMALL)
    line = p.usage_lines()[1]
    shown = repr(raw)[:200]
    assert p.budget.calls[0].actual_usd is None
    assert f"(upstream {shown} unreadable)" in line


_MISSING = object()


@pytest.mark.parametrize(
    "flag",
    [True, "false", 0, _MISSING],
    ids=["True", "false", "0", "missing"],
)
def test_a_null_upstream_keeps_the_reservation_unless_explicitly_non_byok(flag):
    """Null is an absent upstream only when is_byok is boolean false.
    True, a non-boolean flag, or a missing field keeps the reservation."""
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "cost_details": {"upstream_inference_cost": None},
    }
    if flag is not _MISSING:
        usage["is_byok"] = flag
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd is None


@pytest.mark.parametrize("flag", ["false", 0, None])
def test_a_non_boolean_is_byok_still_adds_a_reported_upstream_cost(flag):
    """Anything other than boolean false still adds upstream, so an
    unlabelled call cannot under-count."""
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": flag,
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert p.budget.calls[0].actual_usd == Decimal("1.31")


def test_a_non_byok_call_priced_from_tokens_does_not_add_upstream():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "is_byok": False,
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    # 1000 x 0.000006 + 100 x 0.0000225, and not that sum plus 1.26.
    assert p.budget.calls[0].actual_usd == Decimal("0.00825")


def test_a_refused_unlabelled_call_still_adds_its_upstream_cost():
    """The refusal path settles before it stops the review. A non-boolean
    flag is not proof the cost already includes the provider charge."""
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "is_byok": "false",
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    p, _fake = _no_byok_provider(usage)
    with pytest.raises(ByokRefusedError, match="is not false"):
        p.complete(SMALL)
    assert p.budget.calls[0].actual_usd == Decimal("1.31")


def test_an_upstream_cost_is_added_when_the_call_is_not_marked_byok():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": "0.05",
        "cost_details": {"upstream_inference_cost": "1.26"},
    }
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert p.budget.committed_usd() == Decimal("1.31")


def test_actual_cost_and_usage_are_recorded():
    usage = {"prompt_tokens": 120, "completion_tokens": 40, "cost": "0.0123",
             "completion_tokens_details": {"reasoning_tokens": 7}}  # fmt: skip
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    line = p.usage_lines()[1]
    assert "actual $0.0123" in line
    assert "tokens in=120 out=40 reasoning=7" in line


def test_fallback_cost_includes_a_separate_reasoning_charge():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "completion_tokens_details": {"reasoning_tokens": 40},
    }
    fake = OpenRouterFake(
        reply(completion(usage=usage)),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    p = provider(fake)
    p.complete(SMALL)
    # 1000 x 0.000006 + 100 x 0.0000225 + 40 x 0.00005
    assert p.budget.committed_usd() == Decimal("0.01025")
    assert "cost computed at the highest endpoint rates" in p.usage_lines()[1]


def test_priced_reasoning_without_a_token_count_keeps_the_reservation():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    fake = OpenRouterFake(
        reply(completion(usage=usage)),
        zdr=reply(zdr_payload(pricing={"internal_reasoning": "0.00005"})),
    )
    p = provider(fake)
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]


def test_refusals_before_a_call_are_reported_and_not_counted_as_calls():
    bare = OpenRouterProvider(OpenRouterFake(reply(completion())), KEY)
    with pytest.raises(BudgetRefusedError, match="preflight has not passed"):
        bare.complete(SMALL)
    assert bare.usage_lines()[-1].endswith("0 of 3 calls used")
    assert any(
        "refused: " in line and "preflight" in line for line in bare.usage_lines()
    )

    unpriced = provider(
        OpenRouterFake(reply(completion()), model=reply(catalog(prompt=None)))
    )
    with pytest.raises(PricingUnknownError, match="pricing.prompt is missing"):
        unpriced.complete(SMALL)
    assert unpriced.usage_lines()[-1].endswith("0 of 3 calls used")
    assert any(
        "refused: pricing.prompt is missing" in line for line in unpriced.usage_lines()
    )

    bounded = provider(
        OpenRouterFake(
            reply(completion()),
            zdr=reply(zdr_payload(context_length=20_000)),
        )
    )
    with pytest.raises(BudgetRefusedError, match="context"):
        bounded.complete(SMALL)
    assert bounded.usage_lines()[-1].endswith("0 of 3 calls used")
    assert any(
        line.startswith("refused:") and "context" in line
        for line in bounded.usage_lines()
    )


def test_cost_is_computed_from_catalog_rates_when_not_reported():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual $0.0082" in p.usage_lines()[1]
    assert "cost computed at the highest endpoint rates" in p.usage_lines()[1]


@pytest.mark.parametrize(
    "usage", [{}, {"prompt_tokens": -1_000_000, "completion_tokens": 5}]
)
def test_missing_usage_keeps_the_reservation_as_spent(usage):
    p = provider(OpenRouterFake(reply(completion(usage=usage))))
    p.complete(SMALL)
    assert "actual unknown (counted at the reservation)" in p.usage_lines()[1]


@pytest.mark.parametrize(
    "response,match",
    [
        (completion(model="openai/gpt-5"), "served 'openai/gpt-5'"),
        (completion(model=None), "served None"),
        (completion(model=f"{MODEL_ID}-turbo"), "-turbo'"),
        (completion(model=f"{MODEL_ID}-20261001x"), "20261001x'"),
        (completion(text="  "), "no review text"),
        ({"model": MODEL_ID, "choices": []}, "no review text"),
    ],
)
def test_substituted_models_and_empty_reviews_are_rejected_without_retry(
    response, match
):
    fake = OpenRouterFake(reply(response), reply(completion()))
    with pytest.raises(BoundaryError, match=match):
        provider(fake).complete(SMALL)
    assert len(fake.chat_requests()) == 1


@pytest.mark.parametrize("finish", ["error", "content_filter", None, "tool_calls"])
def test_only_a_stop_finish_is_accepted(finish):
    fake = OpenRouterFake(reply(completion(finish=finish)), reply(completion()))
    p = provider(fake)
    with pytest.raises(BoundaryError, match="did not finish"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    shown = "None" if finish is None else finish
    assert f"incomplete review (finish_reason={shown})" in p.usage_lines()[1]
    assert "actual $0.0123" in p.usage_lines()[1]


def test_a_review_cut_at_the_output_limit_is_settled_and_rejected():
    fake = OpenRouterFake(reply(completion(finish="length")), reply(completion()))
    p = provider(fake)
    with pytest.raises(BoundaryError, match="output-token limit"):
        p.complete(SMALL)
    assert len(fake.chat_requests()) == 1
    line = p.usage_lines()[1]
    assert "incomplete review (finish_reason=length)" in line
    assert "actual $0.0123" in line


def test_dated_variant_of_the_pinned_model_is_accepted():
    fake = OpenRouterFake(reply(completion(model=f"{MODEL_ID}-20261001")))
    assert provider(fake).complete(SMALL) == "review text"


@pytest.mark.parametrize("body", [b"<html>", b'{"a": "\xff"}'])
def test_unparseable_completion_is_settled_and_raised(body):
    p = provider(OpenRouterFake(reply(body)))
    with pytest.raises(BoundaryError, match="non-JSON"):
        p.complete(SMALL)
    assert "unparseable response" in p.usage_lines()[1]


def test_max_price_is_the_pinned_endpoints_highest_price_not_the_catalog_headline():
    """GLM-5.3's catalog headline was $0.084/$3.60 per million and Fireworks
    was $1.40/$4.40. OpenRouter's max_price filter dropped the pin."""
    headline = catalog(prompt="0.000000084", completion="0.0000036", overrides=[])
    rows = zdr_payload(
        providers=("fireworks",),
        pricing={"prompt": "0.0000014", "completion": "0.0000044"},
    )
    fake = OpenRouterFake(
        reply(completion()),
        model=reply(headline),
        zdr=reply(rows),
    )
    adapter = OpenRouterProvider(fake, KEY, providers=("fireworks",))
    adapter.preflight()
    adapter.complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["provider"]["only"] == ["fireworks"]
    assert sent["provider"]["allow_fallbacks"] is False
    assert sent["provider"]["data_collection"] == "deny"
    assert sent["provider"]["zdr"] is True
    assert sent["provider"]["max_price"] == {"prompt": 1.4, "completion": 4.4}
    assert "zdr required: true" in adapter.usage_lines()[0]
    assert "cache_control: true" in adapter.usage_lines()[0]


def test_two_pinned_rows_price_the_dearest_and_not_the_catalog_headline():
    cheap = with_terms(
        {
            "model_id": MODEL_ID,
            "tag": "deepinfra/fp8",
            "safety_retention": False,
            "supported_parameters": ["max_tokens"],
            "pricing": endpoint_price(prompt="0.0000002", completion="0.0000008"),
        }
    )
    dear = with_terms(
        {
            "model_id": MODEL_ID,
            "tag": "deepinfra/fp4",
            "safety_retention": False,
            "supported_parameters": ["max_tokens"],
            "pricing": endpoint_price(prompt="0.0000014", completion="0.0000044"),
        }
    )
    fake = OpenRouterFake(
        reply(completion()),
        model=reply(
            catalog(prompt="0.000000084", completion="0.0000036", overrides=[])
        ),
        zdr=reply({"data": [cheap, dear]}),
    )
    adapter = OpenRouterProvider(
        fake, KEY, providers=("deepinfra/fp8", "deepinfra/fp4")
    )
    adapter.preflight()
    adapter.complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["provider"]["max_price"] == {"prompt": 1.4, "completion": 4.4}
    assert sent["provider"]["only"] == ["deepinfra/fp8", "deepinfra/fp4"]


def test_a_context_smaller_than_the_catalog_refuses_the_one_shot_cap():
    fake = OpenRouterFake(
        reply(completion()),
        zdr=reply(zdr_payload(context_length=16_384, max_completion_tokens=8_192)),
    )
    adapter = provider(fake)
    with pytest.raises(BudgetRefusedError, match="completion limit"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []


def test_an_endpoint_row_without_a_price_is_refused_before_a_call():
    payload = zdr_payload(providers=("amazon-bedrock",))
    del payload["data"][0]["pricing"]
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    with pytest.raises(PricingUnknownError, match="no pricing object"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []


def test_zdr_stays_on_by_default_and_can_be_turned_off():
    on = OpenRouterFake(reply(completion()))
    required = provider(on)
    required.complete(SMALL)
    pinned = json.loads(on.chat_requests()[0][3])
    assert pinned["provider"]["zdr"] is True
    assert pinned["provider"]["data_collection"] == "deny"
    assert pinned["provider"]["allow_fallbacks"] is False
    # Caching is the Anthropic breakpoint, not the ZDR switch. The default
    # rows do not list cache_control, and the request still sends it.
    assert pinned["cache_control"] == {"type": "ephemeral"}
    assert [url for _m, url, _h, _b in on.requests if url.endswith("/endpoints/zdr")]

    off_rows = {
        "data": {
            "id": MODEL_ID,
            "endpoints": [
                {
                    "tag": "amazon-bedrock",
                    "provider_name": "Amazon Bedrock",
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "context_length": 1_000_000,
                    "max_completion_tokens": 64_000,
                    "supported_parameters": ["reasoning", "max_tokens"],
                }
            ],
        }
    }
    off = OpenRouterFake(reply(completion()), endpoints=reply(off_rows))
    relaxed = OpenRouterProvider(off, KEY)
    relaxed.configure(model_route({}, providers="amazon-bedrock", require_zdr=False))
    relaxed.preflight()
    relaxed.complete(SMALL)
    sent = json.loads(off.chat_requests()[0][3])
    assert "zdr" not in sent["provider"]
    assert sent["provider"]["data_collection"] == "deny"
    assert sent["provider"]["allow_fallbacks"] is False
    assert sent["provider"]["only"] == ["amazon-bedrock"]
    assert sent["cache_control"] == {"type": "ephemeral"}
    assert sent["provider"]["max_price"] == {"prompt": 3.0, "completion": 15.0}
    urls = [url for _m, url, _h, _b in off.requests]
    assert f"{API}/models/{MODEL_ID}/endpoints" in urls
    assert f"{API}/endpoints/zdr" in urls
    assert "zdr required: false" in relaxed.usage_lines()[0]
    assert "cache_control: true" in relaxed.usage_lines()[0]


def test_a_display_name_next_to_a_different_tag_is_still_selected():
    """Live rows carry both. `provider_name` is not another spelling of `tag`."""
    payload = zdr_payload(providers=("amazon-bedrock",))
    row = payload["data"][0]
    assert row["tag"] == "amazon-bedrock"
    assert row["provider_name"] == "Amazon Bedrock"
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    adapter.complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["provider"]["only"] == ["amazon-bedrock"]


def test_a_row_with_no_tag_is_not_selected_by_its_display_name():
    payload = zdr_payload(providers=("amazon-bedrock",))
    del payload["data"][0]["tag"]
    payload["data"][0]["provider_name"] = "amazon-bedrock"
    fake = OpenRouterFake(reply(completion()), zdr=reply(payload))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="no ZDR row"):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []


def test_an_endpoint_override_raises_max_price_the_reservation_and_the_fallback():
    rows = zdr_payload(
        providers=("amazon-bedrock",),
        pricing={
            "prompt": "0.000001",
            "completion": "0.000002",
            "input_cache_write": None,
            "overrides": [
                {
                    "prompt": "0.000005",
                    "completion": "0.000010",
                    "min_prompt_tokens": 100_000,
                }
            ],
        },
    )
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "is_byok": False}
    fake = OpenRouterFake(reply(completion(usage=usage)), zdr=reply(rows))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    terms, _selected = adapter.load_terms()
    assert (terms.prompt_rate, terms.completion_rate) == (
        Decimal("0.000005"),
        Decimal("0.000010"),
    )
    assert worst_case_usd(1000, terms, CallLimits()) == Decimal("0.245")
    adapter.complete(SMALL)
    sent = json.loads(fake.chat_requests()[0][3])
    assert sent["provider"]["max_price"] == {"prompt": 5.0, "completion": 10.0}
    assert adapter.budget.calls[0].actual_usd == Decimal("0.006")
    assert "max_price prompt 5.0 completion 10.0" in adapter.usage_lines()[0]
    assert "amazon-bedrock" in adapter.usage_lines()[0]


def test_zdr_off_still_refuses_a_safety_retention_tag_unless_opted_in():
    model = "google/gemini-3.8-flash"
    listed = catalog()
    listed["data"]["id"] = model
    endpoints = {
        "data": {
            "id": model,
            "endpoints": [
                {
                    "tag": "google-vertex/global",
                    "provider_name": "Google",
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "context_length": 1_000_000,
                    "max_completion_tokens": 64_000,
                    "supported_parameters": ["max_tokens"],
                }
            ],
        }
    }
    marked = zdr_payload(
        model, ("google-vertex/global",), safety=True, parameters=["max_tokens"]
    )

    def opened(zdr_reply):
        return OpenRouterFake(
            reply(completion(model=model)),
            model=reply(listed),
            zdr=zdr_reply,
            endpoints=reply(endpoints),
        )

    blocked = opened(reply(marked))
    adapter = OpenRouterProvider(blocked, KEY)
    adapter.configure(
        model_route(
            {},
            model=model,
            providers="google-vertex/global",
            require_zdr=False,
        )
    )
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="Safety Retention"):
        adapter.complete(SMALL)
    assert blocked.chat_requests() == []

    allowed_fake = opened(reply(marked))
    allowed = OpenRouterProvider(allowed_fake, KEY)
    allowed.configure(
        model_route(
            {},
            model=model,
            providers="google-vertex/global",
            require_zdr=False,
            allow_safety_retention=True,
        )
    )
    allowed.preflight()
    assert allowed.complete(SMALL) == "review text"
    sent = json.loads(allowed_fake.chat_requests()[0][3])
    assert "zdr" not in sent["provider"]
    assert sent["provider"]["data_collection"] == "deny"
    assert sent["provider"]["only"] == ["google-vertex/global"]

    unread = opened(reply({}, status=500))
    refused = OpenRouterProvider(unread, KEY)
    refused.configure(
        model_route(
            {},
            model=model,
            providers="google-vertex/global",
            require_zdr=False,
        )
    )
    refused.preflight()
    with pytest.raises(PricingUnknownError, match="HTTP 500"):
        refused.complete(SMALL)
    assert unread.chat_requests() == []


def test_the_one_shot_path_refuses_a_prompt_over_the_row_prompt_ceiling():
    rows = zdr_payload(providers=("amazon-bedrock",))
    rows["data"][0]["max_prompt_tokens"] = 1
    fake = OpenRouterFake(reply(completion()), zdr=reply(rows))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    with pytest.raises(BudgetRefusedError, match="max_prompt_tokens") as raised:
        adapter.complete(SMALL)
    assert "amazon-bedrock" in str(raised.value)
    assert fake.chat_requests() == []


def test_a_malformed_override_names_the_endpoint_row():
    rows = zdr_payload(
        providers=("amazon-bedrock",), pricing={"overrides": "nope"}
    )
    fake = OpenRouterFake(reply(completion()), zdr=reply(rows))
    adapter = OpenRouterProvider(fake, KEY, providers=("amazon-bedrock",))
    adapter.preflight()
    with pytest.raises(
        PricingUnknownError, match=r"endpoint row 0 \(amazon-bedrock\)"
    ):
        adapter.complete(SMALL)
    assert fake.chat_requests() == []
