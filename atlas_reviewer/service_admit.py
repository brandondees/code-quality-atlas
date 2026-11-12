# SPDX-License-Identifier: MIT
"""Decide whether one GitHub webhook delivery becomes a review job. Pure.

The body is untrusted. A delivery is admitted only when the HMAC matches,
the event is a non-draft ``pull_request`` of ``opened``, ``synchronize``
or ``ready_for_review``, and the repository is on the allowlist. Anything
else is ignored. The dedupe key is the repository, the PR number and the
head SHA; this module only names that commit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from atlas_reviewer.domain import InvalidEventError, PrEvent

ACCEPTED_ACTIONS = frozenset({"opened", "synchronize", "ready_for_review"})
SIGNATURE_HEADER = "X-Hub-Signature-256"
EVENT_HEADER = "X-GitHub-Event"
_SHA256_PREFIX = "sha256="
_DIGEST_CHARS = 64


@dataclass(frozen=True)
class Admitted:
    event: PrEvent


@dataclass(frozen=True)
class Ignored:
    """A delivery that will not be reviewed. ``reason`` is a fixed label,
    never text from the payload."""

    reason: str


def signature_matches(body: bytes, header: str | None, secret: str) -> bool:
    """True when ``header`` is the lowercase hex HMAC-SHA256 of ``body``.

    GitHub sends ``sha256=<hex>`` in ``X-Hub-Signature-256``. A missing
    header, a non-sha256 scheme, or a wrong digest is False. The compare
    is constant-time for a well-formed header; a header of any other
    length is rejected before that compare.
    """
    if not secret or not header or not header.startswith(_SHA256_PREFIX):
        return False
    presented = header[len(_SHA256_PREFIX) :]
    if len(presented) != _DIGEST_CHARS:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(presented, digest)


def parse_delivery(body: bytes) -> Any | None:
    """The JSON value, or None when the body is not a JSON object."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def admit(payload: Mapping[str, Any], allowlist: frozenset[str]) -> Admitted | Ignored:
    """Admit one already-authenticated ``pull_request`` payload."""
    action = payload.get("action")
    if action not in ACCEPTED_ACTIONS:
        return Ignored("action")
    pull = payload.get("pull_request")
    repository = payload.get("repository")
    if not isinstance(pull, dict) or not isinstance(repository, dict):
        return Ignored("shape")
    if pull.get("draft") is not False:
        return Ignored("draft")
    repo = repository.get("full_name")
    base = pull.get("base")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    base_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    if not isinstance(repo, str) or repo != base_name:
        return Ignored("repository")
    if repo not in allowlist:
        return Ignored("allowlist")
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    number = pull.get("number")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or not isinstance(sha, str)
    ):
        return Ignored("event")
    try:
        event = PrEvent(repo=repo, pr_number=number, head_sha=sha)
    except InvalidEventError:
        return Ignored("event")
    return Admitted(event)
