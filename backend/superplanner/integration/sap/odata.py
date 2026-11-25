"""Minimal OData client for SAP S/4HANA (M8-DESIGN 9): JSON only (v2 `d.results` / `__next`, v4 `value` /
`@odata.nextLink`), basic auth or OAuth2 client credentials, CSRF token fetch before POST (`x-csrf-token: fetch`,
one retry with a fresh token on 403 "CSRF token validation failed"). The transport is injectable (tests use
`httpx.MockTransport`); real targets pass the M5 URL check (`INTEGRATION_ALLOW_PRIVATE_TARGETS`)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx


class ODataError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


@dataclass
class Client:
    base_url: str
    version: str = "v2"
    username: str = ""
    password: str = ""
    token_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    auth: str = "basic"
    transport: httpx.BaseTransport | None = None
    allow_private: bool = False
    timeout: float = 60.0
    _csrf: dict[str, str] = field(default_factory=dict)
    _token: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.transport is None:
            from ..outbox import check_url

            check_url(self.base_url, self.allow_private)
        self.http = httpx.Client(transport=self.transport, timeout=self.timeout, follow_redirects=False)

    def close(self) -> None:
        self.http.close()

    # -------------------------------------------------- auth

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.auth == "oauth2":
            if self._token is None:
                r = self.http.post(self.token_url, data={"grant_type": "client_credentials",
                                                         "client_id": self.client_id,
                                                         "client_secret": self.client_secret})
                if r.status_code != 200:
                    raise ODataError(r.status_code, "OAuth2 token request failed")
                self._token = r.json()["access_token"]
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _auth(self) -> Any:
        return (self.username, self.password) if self.auth == "basic" and self.username else None

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    # -------------------------------------------------- read

    def get_all(self, path: str, params: dict[str, str] | None = None) -> Iterator[list[dict[str, Any]]]:
        """Pages of records (`$format=json` for v2)."""
        url: str | None = self._url(path)
        q = dict(params or {})
        if self.version == "v2":
            q.setdefault("$format", "json")
        first = True
        while url:
            self.calls.append(("GET", url))
            r = self.http.get(url, params=q if first else None, headers=self._headers(), auth=self._auth())
            first = False
            if r.status_code != 200:
                raise ODataError(r.status_code, _message(r))
            data = r.json()
            recs, url = page_of(data)
            if url:
                url = self._url(url)
            yield recs

    # -------------------------------------------------- write

    def _fetch_token(self, path: str) -> None:
        root = self._url(path.split("/A_")[0] if "/A_" in path else path)
        self.calls.append(("FETCH", root))
        r = self.http.get(root, headers={**self._headers(), "x-csrf-token": "fetch"}, auth=self._auth())
        tok = r.headers.get("x-csrf-token")
        if not tok:
            raise ODataError(r.status_code, "no CSRF token")
        self._csrf = {"x-csrf-token": tok}
        cookies = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else []
        if cookies:
            self._csrf["Cookie"] = "; ".join(c.split(";")[0] for c in cookies)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in (0, 1):
            if not self._csrf:
                self._fetch_token(path)
            url = self._url(path)
            self.calls.append(("POST", url))
            r = self.http.post(url, content=json.dumps(body).encode(), auth=self._auth(),
                               headers={**self._headers(), **self._csrf, "Content-Type": "application/json"})
            if r.status_code == 403 and r.headers.get("x-csrf-token", "").lower() == "required" and attempt == 0:
                self._csrf = {}
                continue
            if r.status_code not in (200, 201, 204):
                raise ODataError(r.status_code, _message(r))
            return r.json() if r.content else {}
        raise ODataError(403, "CSRF token validation failed")  # pragma: no cover


def page_of(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """(records, next link) of a v2 (`d.results`, `d.__next`) or v4 (`value`, `@odata.nextLink`) response."""
    if "d" in data:
        d = data["d"]
        if isinstance(d, dict) and "results" in d:
            return list(d["results"]), d.get("__next")
        return [d], None
    return list(data.get("value", [])), data.get("@odata.nextLink")


def _message(r: httpx.Response) -> str:
    try:
        e = r.json().get("error", {})
        msg = e.get("message")
        if isinstance(msg, dict):
            msg = msg.get("value")
        return str(msg or r.text)[:300]
    except Exception:
        return r.text[:300]
