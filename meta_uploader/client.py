"""A thin Meta Graph API client over `requests`.

Deliberately tiny: GET, POST (incl. multipart), and cursor paging. Nested dict/list
values in POST data are JSON-encoded automatically (the Graph API expects JSON
strings for complex fields like object_story_spec). Errors are mapped to a
MetaError carrying an operator-friendly message + a `fix` hint where useful.
"""

from __future__ import annotations

import json
from typing import Any

import requests

GRAPH_BASE = "https://graph.facebook.com"


class MetaError(Exception):
    """A Meta API / transport failure, phrased for a non-technical operator."""

    def __init__(self, message: str, code: str = "API", fix: str | None = None, raw: Any = None):
        super().__init__(message)
        self.code = code
        self.fix = fix
        self.raw = raw

    def to_dict(self) -> dict:
        out = {"error": str(self), "code": self.code}
        if self.fix:
            out["fix"] = self.fix
        return out


def _encode(data: dict) -> dict:
    """JSON-encode any nested dict/list values; Graph API wants JSON strings."""
    return {
        k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
        for k, v in data.items()
    }


class GraphClient:
    def __init__(
        self,
        access_token: str,
        api_version: str,
        account_id: str | None = None,
        session: requests.Session | None = None,
        base: str = GRAPH_BASE,
    ):
        self.token = access_token
        self.version = api_version
        self.account_id = account_id
        self.base = base.rstrip("/")
        self.session = session or requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base}/{self.version}/{path.lstrip('/')}"

    def get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self.token
        resp = self.session.get(self._url(path), params=params, timeout=60)
        return self._handle(resp)

    def post(self, path: str, data: dict | None = None, files: dict | None = None) -> dict:
        payload = _encode(dict(data or {}))
        payload["access_token"] = self.token
        resp = self.session.post(self._url(path), data=payload, files=files, timeout=300)
        return self._handle(resp)

    def get_all(self, path: str, params: dict | None = None) -> list[dict]:
        """Follow cursor paging and return the concatenated data[] list."""
        out: list[dict] = []
        page = self.get(path, params)
        while True:
            out.extend(page.get("data", []))
            nxt = (page.get("paging") or {}).get("next")
            if not nxt:
                return out
            page = self._handle(self.session.get(nxt, timeout=60))

    def _handle(self, resp: requests.Response) -> dict:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400 or (isinstance(payload, dict) and "error" in payload):
            err = payload.get("error", {}) if isinstance(payload, dict) else {}
            self._raise(resp.status_code, err)
        return payload

    def _raise(self, status: int, err: dict) -> None:
        code = err.get("code")
        message = (
            err.get("error_user_msg")
            or err.get("message")
            or f"Meta API error (HTTP {status})"
        )
        if code == 190:
            raise MetaError(
                "Your Meta connection has expired or is no longer valid.",
                code="AUTH",
                fix=(
                    "Generate a fresh long-lived token (quickstart Part 1, steps "
                    "1.2-1.4), run `python3 -m meta_uploader setup` with the new "
                    "token, then `whoami` to confirm."
                ),
                raw=err,
            )
        raise MetaError(message, code="API", raw=err)
