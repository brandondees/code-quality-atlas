# SPDX-License-Identifier: MIT
"""Live Sprites control-plane adapter (outside API only).

Every request shape here is taken from the published Sprites API OpenAPI
document, version 0.1.12 (https://docs.fly.io/sprites/api/openapi.json,
fetched 2026-11-07), and matches the 2026-11-06 live validation:

- `POST /v1/sprites` `{"name"}` (CreateSpriteRequest), `GET` and `DELETE
  /v1/sprites/{name}`
- `POST|GET /v1/sprites/{name}/policy/network` `{"rules": [...]}`
- `POST /v1/sprites/{name}/policy/resources` `{"memory": {"limit_mb"}}`
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

The token is sent only to the control plane; no method here can pass an
environment, a file, or a connector into a Sprite.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from atlas_reviewer.http import (
    HttpResponse,
    StreamingTransport,
    StreamWindow,
    safe_url,
)
from atlas_reviewer.ports import BoundaryError, Json, NotFoundError

API_URL = "https://api.sprites.dev"
RUNNER_PREFIX = "cqa-rev-"
EXEC_STDIN_MAX_BYTES = 10 * 1024 * 1024


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


def _checked(method: str, url: str, resp: HttpResponse) -> HttpResponse:
    if resp.status == 404:
        raise NotFoundError(f"Sprites 404 for {method} {safe_url(url)}")
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
        resp = self._transport.request(method, url, headers, body, self._timeout_s)
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
