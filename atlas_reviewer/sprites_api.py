# SPDX-License-Identifier: MIT
"""Live Sprites control-plane adapter (outside API only).

Every request shape here is taken from the published Sprites API OpenAPI
document, version 0.1.12 (https://docs.fly.io/sprites/api/openapi.json,
fetched 2026-11-07), and matches the 2026-11-06 live validation:

- `POST /v1/sprites` `{"name"}` (CreateSpriteRequest), `GET` and `DELETE
  /v1/sprites/{name}`
- `POST|GET /v1/sprites/{name}/policy/network` `{"rules": [...]}`
- `POST /v1/sprites/{name}/policy/resources` `{"memory": {"limit_mb"}}`
- `POST /v1/sprites/{name}/checkpoint` `{"comment"}`, `GET /v1/sprites/{name}/checkpoints`, and `POST /v1/sprites/{name}/checkpoints/{checkpoint_id}/restore` (issue #819, D95). Each of the three answers a streaming NDJSON progress whose documented event types are `info`, `error`, `complete` and `keepalive`; an `error` event is the named failure and a `complete` event ends it. The document gives the id no field of its own in the stream -- the completion text carries it ("Checkpoint v3 created successfully") -- so the controller reads the id from the checkpoint list it fetches after the create, whose example shows the newest entry first; whether that ordering, a restore that crosses sprites, and a checkpoint's survival of its sprite's deletion hold live is the live check D95 names.
- `POST /v1/sprites/{name}/exec` (https://docs.fly.io/sprites/api/exec/execute-command):
  argv as repeated `cmd` query parameters, always with `stdin=true` and a
  raw `application/octet-stream` body (empty when there is no input), at
  most 10 MiB (413 above that), so larger stdin is refused before
  sending. The document defines no `tty` parameter (the endpoint is
  "non-TTY only") and says nothing about what a command's stdin is when
  `stdin` is false, so that mode is never used. The `env`, `dir` and
  `path` parameters are never used either, so nothing can be injected
  into a Sprite's environment and `sh` resolves the same way for every
  exec. The 200 response body is not specified by the OpenAPI document;
  see `runner.decode_exec_output`. Exec responses are streamed
  (`http.StreamingTransport`), so a silent command fails at its
  first-byte deadline and a stall keeps the bytes that did arrive.

Control-plane calls go through the same streaming path as exec, with one
wall-clock window of `timeout_s` each, because a plain socket timeout
restarts on every byte: a trickled DELETE or existence check could
otherwise hold cleanup (and the lock the watchdog and the final destroy
share) open indefinitely. Each call is bounded on its own, not by the
review's remaining deadline; `runner.CLEANUP_BUDGET_S` bounds a runner's
cleanup as a whole, so it ends within that budget plus one such window.

The token is sent only to the control plane; no method here can pass an
environment, a file, or a connector into a Sprite.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode

from atlas_reviewer.http import (
    HttpResponse,
    StreamingTransport,
    StreamWindow,
    safe_url,
)
from atlas_reviewer.ports import (
    BoundaryError,
    Json,
    NotFoundError,
    RateLimitedError,
    RefusedError,
)

API_URL = "https://api.sprites.dev"
RUNNER_PREFIX = "cqa-rev-"
EXEC_STDIN_MAX_BYTES = 10 * 1024 * 1024
# The checkpoint-id shape the controller accepts from the API (issue
# #819, D95): the document's examples show short version-like ids ("v7");
# anything outside this charset never reaches a URL path unencoded.
_CHECKPOINT_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


@dataclass(frozen=True)
class ExecRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes


def exec_request(
    api_url: str, sprite_path: str, argv: Sequence[str], stdin: bytes
) -> ExecRequest:
    """The one way an exec request is built, whatever it runs: argv as
    repeated `cmd`, always `stdin=true`, and an octet-stream body that is
    exactly the stdin bytes (possibly none), so the request always ends
    after a known `Content-Length` and the server is never left with an
    open or undocumented stdin. The command side of the same rule is
    `runner.exec_argv`."""
    if not argv:
        raise BoundaryError("exec needs at least one cmd")
    if len(stdin) > EXEC_STDIN_MAX_BYTES:
        raise BoundaryError(
            f"exec stdin is {len(stdin)} bytes, over the documented "
            f"{EXEC_STDIN_MAX_BYTES}-byte limit"
        )
    query = urlencode([*(("cmd", a) for a in argv), ("stdin", "true")])
    return ExecRequest(
        f"{api_url}{sprite_path}/exec?{query}",
        {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(stdin)),
            "Connection": "close",
        },
        stdin,
    )


def parse_retry_after(value: str | None) -> float | None:
    """The seconds a Retry-After header asks the client to wait, or None
    when it is absent or unreadable. RFC 9110 allows a delay in seconds or
    an HTTP-date; an HTTP-date is read against the clock this process sees,
    and a date in the past is no wait at all. Nothing here raises: a value
    it cannot read -- including non-ASCII digit look-alikes, which
    `isdigit` accepts but `float` refuses -- is None, so a caller falls
    back to its own schedule rather than trusting what it cannot read."""
    if value is None:
        return None
    text = value.strip()
    if text.isascii() and text.isdigit():
        return max(float(text), 0.0)
    try:
        when = parsedate_to_datetime(text)
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max((when - datetime.now(UTC)).total_seconds(), 0.0)
    except (ValueError, TypeError, OverflowError):
        return None


def _one_line(text: str, cap: int = 200) -> str:
    flat = " ".join(text.split())
    return flat[:cap]


def _ndjson_complete(raw: bytes, what: str) -> str:
    """The `complete` event's data text from one NDJSON progress stream
    (the shape the document gives the checkpoint create and restore
    responses), or a `BoundaryError` naming `what`: an `error` event is
    the named failure, and a stream with no `complete` event is an
    incomplete one. Unparseable lines are skipped -- a keepalive or a
    future event shape must not fail a stream that completes."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BoundaryError(f"the {what} stream is not UTF-8") from exc
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "error":
            raise BoundaryError(
                f"the {what} failed: {_one_line(str(event.get('error') or 'unspecified'))}"
            )
        if kind == "complete":
            data = event.get("data")
            return data if isinstance(data, str) else ""
    raise BoundaryError(f"the {what} stream carried no complete event")


def _checked(method: str, url: str, resp: HttpResponse) -> HttpResponse:
    if resp.status == 404:
        raise NotFoundError(f"Sprites 404 for {method} {safe_url(url)}")
    if resp.status == 429:
        raise RateLimitedError(
            f"Sprites HTTP 429 for {method} {safe_url(url)}",
            retry_after=parse_retry_after(resp.header("Retry-After")),
        )
    if 400 <= resp.status < 500:
        raise RefusedError(f"Sprites HTTP {resp.status} for {method} {safe_url(url)}")
    if not 200 <= resp.status < 300:
        raise BoundaryError(f"Sprites HTTP {resp.status} for {method} {safe_url(url)}")
    return resp


class SpritesClient:
    def __init__(
        self,
        transport: StreamingTransport,
        token: str,
        api_url: str = API_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self._transport = transport
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s

    def _call(
        self, method: str, path: str, payload: Json | None = None
    ) -> HttpResponse:
        headers = self._headers()
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        url = f"{self._api_url}{path}"
        resp = self._transport.stream(
            method, url, headers, body, StreamWindow(self._timeout_s)
        )
        return _checked(method, url, resp)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "code-quality-atlas-reviewer",
        }

    @staticmethod
    def _path(name: str) -> str:
        if not name.startswith(RUNNER_PREFIX):
            raise BoundaryError(
                f"refusing to manage a Sprite not named {RUNNER_PREFIX}*: {name!r}"
            )
        return f"/v1/sprites/{quote(name, safe='')}"

    def create(self, name: str) -> None:
        self._path(name)
        self._call("POST", "/v1/sprites", {"name": name})

    def set_network_policy(self, name: str, rules: Sequence[Json]) -> None:
        self._call(
            "POST",
            f"{self._path(name)}/policy/network",
            {"rules": [dict(r) for r in rules]},
        )

    def get_network_policy(self, name: str) -> Json:
        resp = self._call("GET", f"{self._path(name)}/policy/network")
        try:
            data = json.loads(resp.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BoundaryError("Sprites network policy read-back is not JSON") from exc
        if not isinstance(data, dict):
            raise BoundaryError("Sprites network policy read-back is not an object")
        return data

    def set_memory_limit(self, name: str, limit_mb: int) -> None:
        self._call(
            "POST",
            f"{self._path(name)}/policy/resources",
            {"memory": {"limit_mb": limit_mb}},
        )

    def exec(
        self,
        name: str,
        argv: Sequence[str],
        stdin: bytes,
        timeout_s: float,
        first_byte_s: float | None = None,
    ) -> bytes:
        request = exec_request(self._api_url, self._path(name), argv, stdin)
        resp = self._transport.stream(
            "POST",
            request.url,
            {**self._headers(), **request.headers},
            request.body,
            StreamWindow(timeout_s, first_byte_s),
        )
        return _checked("POST", request.url, resp).body

    def delete(self, name: str) -> None:
        self._call("DELETE", self._path(name))

    def exists(self, name: str) -> bool:
        try:
            self._call("GET", self._path(name))
        except NotFoundError:
            return False
        return True

    def checkpoint(self, name: str, comment: str) -> str:
        """Creates a checkpoint and returns its id. The create's own NDJSON
        stream carries the id only inside its completion text ("Checkpoint
        v3 created successfully" per the document's example), so the
        parseable source is the checkpoint list read after the create;
        the document's list example shows the newest entry first, which is
        the ordering the first entry relies on (unconfirmed -- the live
        check names it)."""
        resp = self._call(
            "POST", f"{self._path(name)}/checkpoint", {"comment": comment}
        )
        _ndjson_complete(resp.body, "checkpoint create")
        entries = self.list_checkpoints(name)
        if not entries:
            raise BoundaryError("the checkpoint list is empty after a create")
        checkpoint_id = entries[0].get("id")
        if not isinstance(checkpoint_id, str) or not _CHECKPOINT_ID.fullmatch(
            checkpoint_id
        ):
            raise BoundaryError(
                "the newest checkpoint's id is not a usable checkpoint id"
            )
        return checkpoint_id

    def list_checkpoints(self, name: str) -> list[Json]:
        resp = self._call("GET", f"{self._path(name)}/checkpoints")
        try:
            data = json.loads(resp.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BoundaryError("the checkpoint list is not JSON") from exc
        if not isinstance(data, list):
            raise BoundaryError("the checkpoint list is not a list")
        return [entry for entry in data if isinstance(entry, dict)]

    def restore(self, name: str, checkpoint_id: str) -> None:
        if not _CHECKPOINT_ID.fullmatch(checkpoint_id):
            raise BoundaryError(
                "the checkpoint id to restore is not a usable checkpoint id"
            )
        resp = self._call(
            "POST",
            f"{self._path(name)}/checkpoints/{quote(checkpoint_id, safe='')}/restore",
        )
        _ndjson_complete(resp.body, "checkpoint restore")
