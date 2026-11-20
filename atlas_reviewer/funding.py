# SPDX-License-Identifier: MIT
"""The operator's ordered list of model funding sources (D94).

``ATLAS_FUNDING_SOURCES`` names OpenRouter keys in spend order. The
registry stores each key's environment-variable name, never the key.
Unset, empty, or whitespace is no registry: the service keeps today's
single key and today's route. A present value that does not parse, or
that names a missing key variable, is a boot failure.

A key variable is ``ATLAS_OPENROUTER_API_KEY`` (the pilot key this
deployment already holds) or a name under ``ATLAS_FUNDING_``. A name
under ``ATLAS_TENANT_`` is the installation's credential, and the
operator list cannot name it.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

ENV_FUNDING_SOURCES = "ATLAS_FUNDING_SOURCES"
# The chosen source's name and BYOK flag, handed to the one child that
# runs the review. Settings, not credentials: the key itself travels in
# the existing ``ATLAS_OPENROUTER_API_KEY``.
ENV_FUNDING_SOURCE = "ATLAS_FUNDING_SOURCE"
ENV_FUNDING_BYOK = "ATLAS_FUNDING_BYOK"
ENV_MODEL = "ATLAS_MODEL"
PILOT_KEY_ENV = "ATLAS_OPENROUTER_API_KEY"
_FUNDING_KEY_PREFIX = "ATLAS_FUNDING_"
# The setting and the two handoff variables live under the funding
# prefix and are not keys. A source that named one of them would read
# the document, or the source name, as a bearer token.
_NOT_A_KEY = frozenset({ENV_FUNDING_SOURCES, ENV_FUNDING_SOURCE, ENV_FUNDING_BYOK})
_MAX_DOCUMENT_CHARS = 8192
_MAX_SOURCES = 8
# A ceiling above this makes the claim-time over-ceiling check fail to
# skip any key. The single-key parser has no such cap; this one does so
# an extra digit fails at boot instead of disabling that check.
_MAX_CEILING = Decimal(10000)
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_KEY_ENV = re.compile(r"^ATLAS_[A-Z0-9_]+$")
# The same slug grammar ``openrouter._PROVIDER_SLUG`` uses. A test pins
# the two patterns together so a route the child would refuse cannot
# pass the registry.
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9._+-]*(?:/[a-z0-9][a-z0-9._+-]*)*$")
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._+-]*/[a-z0-9][a-z0-9._+-]*$")
# A dollar amount: digits, or digits with one decimal point. This rejects
# the forms ``Decimal`` would otherwise accept, such as ``1e3`` and ``1_000``.
_DOLLAR_AMOUNT = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_FIELDS = frozenset(
    {
        "name",
        "key_env",
        "providers",
        "require_zdr",
        "model_filter",
        "key_ceiling_usd",
        "byok",
    }
)


@dataclass(frozen=True)
class FundingSource:
    """One OpenRouter key and the route a review pinned to it uses."""

    name: str
    key_env: str
    providers: tuple[str, ...]
    require_zdr: bool
    model_filter: str
    key_ceiling_usd: Decimal
    byok: bool

    def allows(self, model_id: str) -> bool:
        """Whether this source may serve ``model_id``.

        ``*`` is every id. ``anthropic/*`` is that vendor's ids, and the
        slash is part of the match, so ``anthropic-lookalike/x`` is not
        an Anthropic id. Anything else is one exact id.
        """
        if self.model_filter == "*":
            return True
        if self.model_filter.endswith("/*"):
            return model_id.startswith(self.model_filter[:-1])
        return model_id == self.model_filter


def load_funding_sources(env: Mapping[str, str]) -> tuple[FundingSource, ...] | None:
    """The operator's sources, in spend order, or None when unset.

    None is today's single key. A present document that is not a
    non-empty array of sources, or whose key variable is missing or
    empty, raises ``ValueError`` naming the setting.
    """
    raw = env.get(ENV_FUNDING_SOURCES)
    if raw is None or raw.strip() == "":
        return None
    if len(raw) > _MAX_DOCUMENT_CHARS:
        raise ValueError(
            f"{ENV_FUNDING_SOURCES} is longer than {_MAX_DOCUMENT_CHARS} characters"
        )
    try:
        data = json.loads(raw, object_pairs_hook=_object)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{ENV_FUNDING_SOURCES} is not JSON: {exc.msg}") from None
    if not isinstance(data, list):
        # ValueError, not TypeError: every malformed document is one boot
        # failure, and config_from_env wraps ValueError into ServiceError.
        raise ValueError(  # noqa: TRY004
            f"{ENV_FUNDING_SOURCES} must be a JSON array of sources"
        )
    if not data:
        raise ValueError(f"{ENV_FUNDING_SOURCES} names no sources")
    if len(data) > _MAX_SOURCES:
        raise ValueError(
            f"{ENV_FUNDING_SOURCES} names {len(data)} sources; the limit is {_MAX_SOURCES}"
        )
    sources: list[FundingSource] = []
    names: set[str] = set()
    key_envs: set[str] = set()
    for index, item in enumerate(data):
        source = _source(item, index)
        if source.name in names:
            raise ValueError(
                f"{ENV_FUNDING_SOURCES} source {index} repeats the name {source.name!r}"
            )
        if source.key_env in key_envs:
            raise ValueError(
                f"{ENV_FUNDING_SOURCES} source {index} repeats the key variable "
                f"{source.key_env}"
            )
        key = env.get(source.key_env)
        if key is None or key.strip() == "":
            raise ValueError(
                f"{ENV_FUNDING_SOURCES} source {source.name!r} names {source.key_env}, "
                "which is unset"
            )
        names.add(source.name)
        key_envs.add(source.key_env)
        sources.append(source)
    return tuple(sources)


def sources_cover(sources: tuple[FundingSource, ...], model_id: str) -> None:
    """Fail when no source's filter matches the model the service will ask for."""
    if _MODEL_ID.fullmatch(model_id) is None:
        raise ValueError(f"{ENV_MODEL} {model_id!r} is not an OpenRouter model id")
    if any(source.allows(model_id) for source in sources):
        return
    raise ValueError(
        f"{ENV_FUNDING_SOURCES} has no source whose model filter matches {model_id}"
    )


def configured_model(env: Mapping[str, str], default: str) -> str:
    """The model id the service will ask for: ``ATLAS_MODEL`` when it is
    set, otherwise ``default``. A set value that is not a model id is a
    boot failure."""
    raw = env.get(ENV_MODEL)
    if raw is None or raw.strip() == "":
        return default
    model = raw.strip()
    if _MODEL_ID.fullmatch(model) is None:
        raise ValueError(f"{ENV_MODEL} {model!r} is not an OpenRouter model id")
    return model


def noted_funding_source(env: Mapping[str, str] | None = None) -> str:
    """The source name a child was handed, or "" when it was not.

    The child prints this on the cost line and the progress record. A
    value that is not a source name is ignored, so a stray variable
    cannot put arbitrary text on the draft.
    """
    source = os.environ if env is None else env
    raw = source.get(ENV_FUNDING_SOURCE, "").strip()
    if _NAME.fullmatch(raw) is None:
        return ""
    return raw


def funding_byok(env: Mapping[str, str] | None = None) -> bool:
    """True only when the child was handed a BYOK source.

    Unset is false, which is today's classification: an HTTP 400 stays a
    per-call error. Only the exact word ``true`` opts in.
    """
    source = os.environ if env is None else env
    return source.get(ENV_FUNDING_BYOK, "").strip() == "true"


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """One JSON object, refusing a field that appears twice.

    ``json.loads`` otherwise keeps the last value, and the missing-field
    check would then accept a document that names two different sources
    under one ``name``.
    """
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"{ENV_FUNDING_SOURCES} repeats the field {key!r}")
        data[key] = value
    return data


def _source(item: object, index: int) -> FundingSource:
    where = f"{ENV_FUNDING_SOURCES} source {index}"
    if not isinstance(item, dict):
        raise ValueError(f"{where} is not an object")  # noqa: TRY004
    extra = set(item) - _FIELDS
    missing = _FIELDS - set(item)
    if extra or missing:
        raise ValueError(
            f"{where} must carry exactly {sorted(_FIELDS)}; "
            f"extra {sorted(extra)}, missing {sorted(missing)}"
        )
    name = item["name"]
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(f"{where} has a name that is not a short token: {name!r}")
    if name.startswith(("atlas-tenant", "atlas_tenant")):
        raise ValueError(f"{where} name {name!r} is in the tenant namespace")
    key_env = _key_env(item["key_env"], where)
    providers = _providers(item["providers"], where)
    require_zdr = _bool(item["require_zdr"], where, "require_zdr")
    model_filter = _filter(item["model_filter"], where)
    ceiling = _ceiling(item["key_ceiling_usd"], where)
    # byok and require_zdr are independent. A source that declares both
    # is the operator's claim; the child fails at the ZDR preflight.
    # This parser does not add a joint rule, and claim time does not either.
    byok = _bool(item["byok"], where, "byok")
    return FundingSource(
        name, key_env, providers, require_zdr, model_filter, ceiling, byok
    )


def _key_env(value: object, where: str) -> str:
    if not isinstance(value, str) or _KEY_ENV.fullmatch(value) is None:
        raise ValueError(f"{where} has a key variable that is not an ATLAS name")
    if value.startswith("ATLAS_TENANT"):
        raise ValueError(f"{where} key variable {value} is a tenant credential")
    if value in _NOT_A_KEY:
        raise ValueError(f"{where} key variable {value} is not a key")
    if value == PILOT_KEY_ENV:
        return value
    if value.startswith(_FUNDING_KEY_PREFIX) and len(value) > len(_FUNDING_KEY_PREFIX):
        return value
    raise ValueError(
        f"{where} key variable {value} must be {PILOT_KEY_ENV} or a name "
        f"under {_FUNDING_KEY_PREFIX}"
    )


def _providers(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} needs a non-empty providers list")
    slugs: list[str] = []
    for slug in value:
        if not isinstance(slug, str) or _PROVIDER.fullmatch(slug) is None:
            raise ValueError(f"{where} has a provider slug {slug!r}")
        if slug in slugs:
            raise ValueError(f"{where} repeats the provider slug {slug!r}")
        slugs.append(slug)
    return tuple(slugs)


def _bool(value: object, where: str, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(  # noqa: TRY004
            f"{where} field {field} must be a boolean, not {value!r}"
        )
    return value


def _filter(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where} model filter is not a string")  # noqa: TRY004
    if value == "*":
        return value
    if value.endswith("/*"):
        prefix = value[:-2]
        if _PROVIDER.fullmatch(prefix) is None or "/" in prefix:
            raise ValueError(f"{where} model filter {value!r} is not a vendor prefix")
        return value
    if _MODEL_ID.fullmatch(value) is None:
        raise ValueError(
            f"{where} model filter {value!r} is not a model id or a prefix"
        )
    return value


def _ceiling(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(  # noqa: TRY004
            f"{where} key ceiling must be a whole number or a decimal string"
        )
    raw = value.strip() if isinstance(value, str) else str(value)
    if _DOLLAR_AMOUNT.fullmatch(raw) is None:
        raise ValueError(f"{where} key ceiling {value!r} is not a dollar amount")
    amount = Decimal(raw)
    if not amount.is_finite() or amount <= 0 or amount > _MAX_CEILING:
        raise ValueError(
            f"{where} key ceiling must be greater than 0 and at most {_MAX_CEILING}"
        )
    return amount
