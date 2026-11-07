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
  argv as repeated `cmd` query parameters; `stdin=true` only when a body
  is sent; the body is raw `application/octet-stream`, at most 10 MiB
  (413 above that), so larger stdin is refused before sending. The `env`
  query parameter is never used, so nothing can be injected into a
  Sprite's environment. The 200 response body is not specified by the
  OpenAPI document; see `runner.decode_exec_output`.

The token is sent only to the control plane; no method here can pass an
environment, a file, or a connector into a Sprite.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from urllib.parse import quote, urlencode

from atlas_reviewer.http import HttpResponse, Transport, safe_url
from atlas_reviewer.ports import BoundaryError, Json, NotFoundError

API_URL = "https://api.sprites.dev"
RUNNER_PREFIX = "cqa-rev-"
EXEC_STDIN_MAX_BYTES = 10 * 1024 * 1024


class SpritesClient:
    def __init__(
        self,
        transport: Transport,
        token: str,
        api_url: str = API_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self._transport = transport
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._timeout_s = timeout_s

    def _call(
        self,
        method: str,
        path: str,
        payload: Json | None = None,
        raw_body: bytes | None = None,
        timeout_s: float | None = None,
    ) -> HttpResponse:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "code-quality-atlas-reviewer",
        }
        body = raw_body
        if raw_body is not None:
            headers["Content-Type"] = "application/octet-stream"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        url = f"{self._api_url}{path}"
        resp = self._transport.request(
            method, url, headers, body, timeout_s or self._timeout_s
        )
        if resp.status == 404:
            raise NotFoundError(f"Sprites 404 for {method} {safe_url(url)}")
        if not 200 <= resp.status < 300:
            raise BoundaryError(
                f"Sprites HTTP {resp.status} for {method} {safe_url(url)}"
            )
        return resp

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
        except json.JSONDecodeError as exc:
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
        self, name: str, argv: Sequence[str], stdin: bytes, timeout_s: float
    ) -> bytes:
        if not argv:
            raise BoundaryError("exec needs at least one cmd")
        if len(stdin) > EXEC_STDIN_MAX_BYTES:
            raise BoundaryError(
                f"exec stdin is {len(stdin)} bytes, over the documented "
                f"{EXEC_STDIN_MAX_BYTES}-byte limit"
            )
        params = [("cmd", a) for a in argv] + ([("stdin", "true")] if stdin else [])
        return self._call(
            "POST",
            f"{self._path(name)}/exec?{urlencode(params)}",
            raw_body=stdin or None,
            timeout_s=timeout_s,
        ).body

    def delete(self, name: str) -> None:
        self._call("DELETE", self._path(name))

    def exists(self, name: str) -> bool:
        try:
            self._call("GET", self._path(name))
        except NotFoundError:
            return False
        return True
