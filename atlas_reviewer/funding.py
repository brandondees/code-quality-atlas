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

import contextvars
import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from atlas_reviewer.http import UrllibTransport, safe_url
from atlas_reviewer.ports import (
    KEY_AUTH_REFUSED,
    KEY_OUT_OF_CREDIT,
    BoundaryError,
    KeyRefusedError,
)
from atlas_reviewer.pricing import KeyStatus, PricingUnknownError, parse_key_status

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
# The source-name grammar and the exhaustion notice are one text.
# `known_review_error` parses what `unavailable_notice` builds. A second
# copy would let a wording change here make a retry post nothing.
SOURCE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_NAME = SOURCE_NAME
NOTICE_PREFIX = "no funding source is available: "
NOTICE_SEPARATOR = "; "
NOTICE_CAUSE_MARK = ": "
UNAVAILABLE_CAUSE = "unavailable"
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
        # The refusal names the source's position and the defect. A name,
        # field, value, or slug from the document can be a pasted key, and
        # config_from_env prints this message on stderr.
        if source.name in names:
            raise ValueError(f"{ENV_FUNDING_SOURCES} source {index} repeats the name")
        if source.key_env in key_envs:
            raise ValueError(
                f"{ENV_FUNDING_SOURCES} source {index} repeats the key variable"
            )
        key = env.get(source.key_env)
        if key is None or key.strip() == "":
            raise ValueError(
                f"{ENV_FUNDING_SOURCES} source {index} names a key variable "
                "which is unset"
            )
        names.add(source.name)
        key_envs.add(source.key_env)
        sources.append(source)
    return tuple(sources)


def sources_cover(sources: tuple[FundingSource, ...], model_id: str) -> None:
    """Fail when no source's filter matches the model the service will ask for."""
    if _MODEL_ID.fullmatch(model_id) is None:
        raise ValueError(f"{ENV_MODEL} is not an OpenRouter model id")
    if any(source.allows(model_id) for source in sources):
        return
    raise ValueError(
        f"{ENV_FUNDING_SOURCES} has no source whose model filter matches "
        "the configured model"
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
        raise ValueError(f"{ENV_MODEL} is not an OpenRouter model id")
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


KEY_URL = "https://openrouter.ai/api/v1/key"
_PROBE_TIMEOUT_S = 15.0
_REFUSAL_CAUSES = frozenset({KEY_OUT_OF_CREDIT, KEY_AUTH_REFUSED})


@dataclass(frozen=True)
class FundingChoice:
    """The one source a review was pinned to at claim time.

    ``key`` is the credential the child receives as
    ``ATLAS_OPENROUTER_API_KEY``. It is not logged and it is not written
    on the draft."""

    name: str
    key: str = field(repr=False)
    providers: tuple[str, ...]
    require_zdr: bool
    key_ceiling_usd: Decimal
    byok: bool


@dataclass(frozen=True)
class FundingSelection:
    """What claim time decided.

    ``choice`` is the source the review runs on. ``refusal`` is a D92
    cause, set only when every source that could serve the model has
    refused or is out of credit. ``error`` is any other reason no
    source was chosen — a probe that failed, a key over its ceiling.
    That selection is not itself a D92 post. The worker posts one when
    this head already advanced, and the cause is the one recorded for
    this head. When every source is already unavailable and this head
    has no recorded cause, the worker posts the selector's notice:
    no funding source is available, then each source and its cause.
    A probe failure while a source is still eligible posts nothing."""

    choice: FundingChoice | None = None
    refusal: str = ""
    error: str = ""


# The source the worker pinned for this claim. The child handoff reads
# it. Unset is no operator source.
active_choice: contextvars.ContextVar[FundingChoice | None] = contextvars.ContextVar(
    "atlas_funding_choice", default=None
)


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
            raise ValueError(f"{ENV_FUNDING_SOURCES} repeats the field")
        data[key] = value
    return data


def accepted_source_name(value: object) -> str | None:
    """A source name, ``""`` when the field is present and blank, None
    when the value cannot be a source name."""
    if value == "":
        return ""
    if isinstance(value, str) and _NAME.fullmatch(value) is not None:
        return value
    return None


def funding_key_values(env: Mapping[str, str]) -> tuple[str, ...]:
    """The funding keys a log has to scrub. A value shorter than 8
    characters is left alone, the same bar the other secret scrubbing
    uses. An unreadable document yields nothing: boot already refused it."""
    try:
        sources = load_funding_sources(env)
    except ValueError:
        return ()
    if sources is None:
        return ()
    values: list[str] = []
    for source in sources:
        key = env.get(source.key_env, "")
        if len(key) >= 8 and key not in values:
            values.append(key)
    return tuple(values)


def key_probe(key: str) -> KeyStatus:
    """``GET /api/v1/key`` for one OpenRouter key.

    A 401 or 402 is a key refusal. Anything else that is not a 200 is a
    boundary error, so the caller can try another source without
    treating a transient failure as a dry key. The error text is the
    status and the URL, never the body and never the key. The transport
    does not follow redirects, so the bearer token stays on this host.
    """
    # openrouter imports budget. Keeping this import in the function lets
    # budget import this module without a cycle.
    from atlas_reviewer.openrouter import _json_object, key_refusal_or_boundary

    transport = UrllibTransport()
    response = transport.request(
        "GET",
        KEY_URL,
        {
            "User-Agent": "code-quality-atlas-reviewer",
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
        },
        None,
        _PROBE_TIMEOUT_S,
    )
    where = safe_url(KEY_URL)
    message = f"OpenRouter HTTP {response.status} for {where}"
    if response.status != 200:
        raise key_refusal_or_boundary(response.status, message)
    return parse_key_status(_json_object(response.body, where, PricingUnknownError))


class FundingSelector:
    """Picks the first source that can fund one review.

    The unavailable set is this process's memory of keys that refused.
    A restart forgets it, and the next probe decides again. Choosing and
    marking share one lock: more than one review can be claimed at once.
    """

    def __init__(
        self,
        sources: tuple[FundingSource, ...],
        env: Mapping[str, str],
        probe: Callable[[str], KeyStatus],
        model: str,
    ) -> None:
        self._sources = sources
        self._env = env
        self._probe = probe
        self._model = model
        self._lock = threading.Lock()
        self._unavailable: set[str] = set()
        self._causes: dict[str, str] = {}

    def choose(self) -> FundingSelection:
        """Walk the sources in order. The key probe runs outside the
        lock, so one claim's HTTPS call does not stall another claim
        or a refusal mark. Two claims can probe the same key; both may
        take it. The refusal, when every matching source has refused,
        is the first refused source's cause in spend order."""
        reasons: list[str] = []
        for source in self._sources:
            with self._lock:
                if not source.allows(self._model) or source.name in self._unavailable:
                    continue
            outcome = self._probe_source(source)
            with self._lock:
                if source.name in self._unavailable:
                    continue
                if isinstance(outcome, FundingChoice):
                    return FundingSelection(choice=outcome)
                if outcome in _REFUSAL_CAUSES:
                    self._refuse(source.name, outcome)
                    continue
                reasons.append(outcome)
        with self._lock:
            if reasons:
                return FundingSelection(
                    error=(
                        "no funding source is available for this review: "
                        + "; ".join(reasons)
                    )
                )
            cause = self._remembered_cause()
        if cause:
            return FundingSelection(refusal=cause)
        return FundingSelection(error="no funding source is available for this review")

    def mark_refused(self, name: str, cause: str = KEY_OUT_OF_CREDIT) -> bool:
        """Remember that ``name`` refused. True when another source can
        still serve the model.

        The selector's lock test calls it while a probe is in flight, and
        the next-claim test calls it to skip a source.
        ``Worker._advance_on_refusal`` calls it when a review's key
        refuses. ``cause`` is the D92 text a later claim posts when
        nothing else can serve."""
        with self._lock:
            self._unavailable.add(name)
            if cause in _REFUSAL_CAUSES:
                self._causes[name] = cause
            return self._another_available()

    def unavailable_notice(self) -> str:
        """The D92 text when every source this model can use is already
        unavailable, or empty when one can still be probed.

        Each name is paired with its recorded cause, in spend order. A
        cause is the fixed D92 text. The notice carries no key. Empty
        when a source is still eligible, including one whose last probe
        failed: that source is not marked unavailable, so the next claim
        can try it."""
        with self._lock:
            parts: list[str] = []
            for source in self._sources:
                if not source.allows(self._model):
                    continue
                if source.name not in self._unavailable:
                    return ""
                cause = self._causes.get(source.name, "")
                shown = cause if cause else UNAVAILABLE_CAUSE
                parts.append(f"{source.name}{NOTICE_CAUSE_MARK}{shown}")
            if not parts:
                return ""
            return NOTICE_PREFIX + NOTICE_SEPARATOR.join(parts)

    def unavailable_names(self) -> tuple[str, ...]:
        """Sources this model would skip because they already refused,
        in spend order. Names only."""
        with self._lock:
            return tuple(
                source.name
                for source in self._sources
                if source.allows(self._model) and source.name in self._unavailable
            )

    def _probe_source(self, source: FundingSource) -> FundingChoice | str:
        """A choice, a D92 cause, or a reason the source was skipped
        without being marked unavailable. The reason names the source
        and not the key. This does not touch the unavailable set; the
        caller records a refusal under the lock."""
        key = self._env.get(source.key_env, "")
        if key.strip() == "":
            return f"{source.name}: the key is unset"
        try:
            status = self._probe(key)
        except KeyRefusedError as exc:
            if exc.review_error not in _REFUSAL_CAUSES:
                return (
                    f"{source.name}: the probe refused for a reason "
                    "that is not a key refusal"
                )
            return exc.review_error
        except (BoundaryError, PricingUnknownError):
            # A 500, a non-JSON 200, or an unlimited key is not a refusal.
            # The selection fails closed and the next claim can try again.
            return f"{source.name}: the key probe failed"
        if status.limit > source.key_ceiling_usd:
            return f"{source.name}: the key limit is over the source ceiling"
        if status.limit_remaining <= 0:
            return KEY_OUT_OF_CREDIT
        return FundingChoice(
            source.name,
            key,
            source.providers,
            source.require_zdr,
            source.key_ceiling_usd,
            source.byok,
        )

    def _refuse(self, name: str, cause: str) -> None:
        self._unavailable.add(name)
        self._causes[name] = cause

    def _remembered_cause(self) -> str:
        """The first refused source's cause, in spend order.

        A later source's 401 does not replace an earlier source's
        out-of-credit cause. The post names the source the registry
        would have tried first.
        """
        for source in self._sources:
            if source.allows(self._model) and source.name in self._causes:
                return self._causes[source.name]
        return ""

    def _another_available(self) -> bool:
        return any(
            source.allows(self._model) and source.name not in self._unavailable
            for source in self._sources
        )


def _source(item: object, index: int) -> FundingSource:
    where = f"{ENV_FUNDING_SOURCES} source {index}"
    if not isinstance(item, dict):
        raise ValueError(f"{where} is not an object")  # noqa: TRY004
    extra = set(item) - _FIELDS
    missing = _FIELDS - set(item)
    if extra:
        raise ValueError(f"{where} has an extra field")
    if missing:
        raise ValueError(f"{where} is missing a field")
    name = item["name"]
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ValueError(f"{where} has a name that is not a short token")
    if name.startswith("atlas-tenant"):
        raise ValueError(f"{where} name is in the tenant namespace")
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
        raise ValueError(f"{where} key variable is a tenant credential")
    if value in _NOT_A_KEY:
        raise ValueError(f"{where} key variable is not a key")
    if value == PILOT_KEY_ENV:
        return value
    if value.startswith(_FUNDING_KEY_PREFIX) and len(value) > len(_FUNDING_KEY_PREFIX):
        return value
    raise ValueError(f"{where} key variable must be the pilot key or a funding key")


def _providers(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} needs a non-empty providers list")
    slugs: list[str] = []
    for slug in value:
        if not isinstance(slug, str) or _PROVIDER.fullmatch(slug) is None:
            raise ValueError(f"{where} has a provider slug that is not a slug")
        if slug in slugs:
            raise ValueError(f"{where} repeats the provider slug")
        slugs.append(slug)
    return tuple(slugs)


def _bool(value: object, where: str, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(  # noqa: TRY004
            f"{where} field {field} must be a boolean"
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
            raise ValueError(f"{where} model filter is not a vendor prefix")
        return value
    if _MODEL_ID.fullmatch(value) is None:
        raise ValueError(f"{where} model filter is not a model id or a prefix")
    return value


def _ceiling(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(  # noqa: TRY004
            f"{where} key ceiling must be a whole number or a decimal string"
        )
    raw = value.strip() if isinstance(value, str) else str(value)
    if _DOLLAR_AMOUNT.fullmatch(raw) is None:
        raise ValueError(f"{where} key ceiling is not a dollar amount")
    amount = Decimal(raw)
    if not amount.is_finite() or amount <= 0 or amount > _MAX_CEILING:
        raise ValueError(
            f"{where} key ceiling must be greater than 0 and at most {_MAX_CEILING}"
        )
    return amount
