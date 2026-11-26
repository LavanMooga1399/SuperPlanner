"""Minimal OData client for SAP S/4HANA (M8-DESIGN 9): JSON only (v2 `d.results` / `__next`, v4 `value` /
`@odata.nextLink`), basic auth or OAuth2 client credentials, CSRF token fetch before POST (`x-csrf-token: fetch`,
one retry with a fresh token on 403 "CSRF token validation failed").

SSRF (review 2): every request - base URL, OAuth2 token URL, next links - goes through `PinnedTransport`: the M5
check (`resolve_checked`: https only, no credentials in the URL, public addresses unless
`INTEGRATION_ALLOW_PRIVATE_TARGETS`) and a connection to exactly the checked address (no second DNS lookup;
optional CONNECT proxy). Next links are followed only for the base URL's scheme, host and port; redirects never.
Paging is server driven (review 4): `Prefer: odata.maxpagesize=<n>` and the server's next links, never `$top`.
Errors carry the HTTP status and a short code, never the response body. Tests inject an `httpx.MockTransport`."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import httpx

MAX_BODY = 64 * 1024 * 1024


class ODataError(Exception):
    """`code` is short and safe to store (no response body)."""

    def __init__(self, status: int, code: str):
        super().__init__(f"{status}: {code}")
        self.status = status
        self.code = code
        self.message = code


class PinnedTransport(httpx.BaseTransport):
    """httpx transport over the M5 pinned HTTPS connection (SSRF-checked address, TLS to the host name)."""

    def __init__(self, allow_private: bool, timeout: float = 60.0, proxy: dict[str, Any] | None = None,
                 context: ssl.SSLContext | None = None):
        self.allow_private = allow_private
        self.timeout = timeout
        self.proxy = proxy
        self.context = context or ssl.create_default_context()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        from ..outbox import _PinnedHTTPSConnection, _bypass, resolve_checked

        url = str(request.url)
        host, port, addrs = resolve_checked(url, self.allow_private)
        proxy = None if (self.proxy is None or _bypass(host)) else self.proxy
        u = urlparse(url)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        headers["Host"] = host if port == 443 else f"{host}:{port}"
        body = request.read()
        last: Exception | None = None
        for ip in addrs[:3]:
            conn = _PinnedHTTPSConnection(host, ip, port, self.timeout, self.context, proxy)
            try:
                conn.request(request.method, path, body=body or None, headers=headers)
                r = conn.getresponse()
                data = r.read(MAX_BODY)
                return httpx.Response(r.status, headers=r.getheaders(), content=data, request=request)
            except OSError as e:
                last = e
            finally:
                conn.close()
        raise httpx.ConnectError(f"connection failed ({last.__class__.__name__ if last else 'no address'})",
                                 request=request)


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
    page_size: int = 2000
    proxy: dict[str, Any] | None = None
    _csrf: dict[str, str] = field(default_factory=dict)
    _token: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        transport = self.transport or PinnedTransport(self.allow_private, self.timeout, self.proxy)
        b = urlparse(self.base_url)
        self._origin = (b.scheme, (b.hostname or "").lower(), b.port or (443 if b.scheme == "https" else 80))
        self.http = httpx.Client(transport=transport, timeout=self.timeout, follow_redirects=False)

    def _same_origin(self, url: str) -> bool:
        u = urlparse(url)
        return (u.scheme, (u.hostname or "").lower(), u.port or (443 if u.scheme == "https" else 80)) == self._origin

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
                    raise ODataError(r.status_code, "SAP_OAUTH_FAILED")
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
        q.pop("$top", None)                                   # server-driven paging only
        if self.version == "v2":
            q.setdefault("$format", "json")
        first = True
        while url:
            self.calls.append(("GET", url))
            r = self.http.get(url, params=q if first else None, auth=self._auth(),
                              headers={**self._headers(), "Prefer": f"odata.maxpagesize={self.page_size}"})
            first = False
            if r.status_code != 200:
                raise ODataError(r.status_code, _code(r))
            try:
                data = r.json()
            except ValueError:
                raise ODataError(r.status_code, "SAP_BAD_JSON") from None
            recs, url = page_of(data)
            if url:
                url = self._url(url)
                if not self._same_origin(url):
                    raise ODataError(0, "SAP_FOREIGN_NEXT_LINK")
            yield recs

    # -------------------------------------------------- write

    def _fetch_token(self, path: str) -> None:
        root = self._url(path.split("/A_")[0] if "/A_" in path else path)
        self.calls.append(("FETCH", root))
        r = self.http.get(root, headers={**self._headers(), "x-csrf-token": "fetch"}, auth=self._auth())
        tok = r.headers.get("x-csrf-token")
        if not tok:
            raise ODataError(r.status_code, "SAP_NO_CSRF_TOKEN")
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
                raise ODataError(r.status_code, _code(r))
            return r.json() if r.content else {}
        raise ODataError(403, "SAP_CSRF_FAILED")  # pragma: no cover


def page_of(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """(records, next link) of a v2 (`d.results`, `d.__next`) or v4 (`value`, `@odata.nextLink`) response."""
    if "d" in data:
        d = data["d"]
        if isinstance(d, dict) and "results" in d:
            return list(d["results"]), d.get("__next")
        return [d], None
    return list(data.get("value", [])), data.get("@odata.nextLink")


def _code(r: httpx.Response) -> str:
    """A short, safe error code: the OData error code when it is a plain identifier, else `HTTP_<status>`."""
    import re

    try:
        c = str(r.json().get("error", {}).get("code") or "")
    except Exception:
        c = ""
    return c[:40] if re.fullmatch(r"[A-Za-z0-9_/.\-]{1,40}", c) else f"HTTP_{r.status_code}"
