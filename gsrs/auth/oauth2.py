"""OAuth2 authentication: the token provider and its bearer handler.

The provider and the handler live together so the handler can use the provider
without importing :mod:`gsrs.client.http`, and the provider reaches the
proxy/TLS helpers through the lower :mod:`gsrs.transport` layer.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping
from json import JSONDecodeError
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import (
    AbstractBasicAuthHandler,
    HTTPPasswordMgr,
    Request,
)

from gsrs.exceptions import (
    ApiResponseError,
    HttpRequestError,
    HttpTransportError,
)
from gsrs.transport import (
    NoProxyConfig,
    ProxyConfig,
    _build_url_opener,
    _normalize_no_proxy,
    _normalize_proxies,
)

from .base import AuthHandler

__all__ = [
    "OAuth2AuthHandler",
    "OAuth2Token",
]


class OAuth2Token:
    """OAuth2 bearer token provider with caching and automatic refresh.

    Tokens are requested from ``token_url`` with the ``client_credentials`` or
    ``password`` grant and re-requested once they expire (``expires_in`` minus
    ``leeway`` seconds). Call :meth:`invalidate` to force a refresh, for example
    after the API answered with ``401 Unauthorized``.

    Set ``verify_ssl`` to ``False`` to accept self-signed certificates from the
    OAuth2 token endpoint.

    Set ``proxy`` to a proxy URL (or a mapping of scheme to proxy URL) to route
    token requests through a proxy. ``no_proxy`` lists hosts that bypass it.
    """

    SUPPORTED_GRANT_TYPES = ("client_credentials", "password")
    SUPPORTED_CLIENT_AUTH = ("basic", "body")

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str | None = None,
        scope: str | None = None,
        grant_type: str = "client_credentials",
        username: str | None = None,
        password: str | None = None,
        audience: str | None = None,
        extra_params: Mapping[str, Any] | None = None,
        client_auth: str = "basic",
        verify_ssl: bool = True,
        proxy: ProxyConfig = None,
        no_proxy: NoProxyConfig = None,
        timeout: float = 30.0,
        leeway: float = 30.0,
        opener: Any = None,
    ) -> None:
        if not token_url:
            raise ValueError("OAuth2 token_url is required.")
        if not client_id:
            raise ValueError("OAuth2 client_id is required.")
        if grant_type not in self.SUPPORTED_GRANT_TYPES:
            supported = ", ".join(self.SUPPORTED_GRANT_TYPES)
            raise ValueError(
                f"Unsupported OAuth2 grant_type {grant_type!r}. Supported values: {supported}."
            )
        if grant_type == "password" and (username is None or password is None):
            raise ValueError("The OAuth2 password grant requires username and password.")
        if client_auth not in self.SUPPORTED_CLIENT_AUTH:
            supported = ", ".join(self.SUPPORTED_CLIENT_AUTH)
            raise ValueError(
                f"Unsupported OAuth2 client_auth {client_auth!r}. Supported values: {supported}."
            )

        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.grant_type = grant_type
        self.username = username
        self.password = password
        self.audience = audience
        self.extra_params = dict(extra_params or {})
        self.client_auth = client_auth
        self.verify_ssl = verify_ssl
        self.proxy = _normalize_proxies(proxy)
        self.no_proxy = _normalize_no_proxy(no_proxy)
        self.timeout = timeout
        self.leeway = leeway
        self._opener = opener or _build_url_opener(
            verify_ssl=verify_ssl,
            proxy=proxy,
            no_proxy=no_proxy,
        )
        self._lock = Lock()
        self._access_token: str | None = None
        self._expires_at: float | None = None

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> OAuth2Token:
        """Build a provider from a mapping of :meth:`__init__` arguments."""
        return cls(**dict(config))

    @property
    def token(self) -> str:
        """Return a valid access token, requesting a new one when necessary."""
        with self._lock:
            if self._access_token is None or self._is_expired():
                self._access_token, self._expires_at = self._fetch_token()
            return self._access_token

    @property
    def authorization_header(self) -> str:
        return f"Bearer {self.token}"

    def invalidate(self) -> None:
        """Drop the cached token so the next request fetches a fresh one."""
        with self._lock:
            self._access_token = None
            self._expires_at = None

    def close(self) -> None:
        self.invalidate()
        self._opener = None

    def _is_expired(self) -> bool:
        return self._expires_at is not None and time.monotonic() >= self._expires_at

    def _fetch_token(self) -> tuple[str, float | None]:
        form: dict[str, Any] = {"grant_type": self.grant_type}
        if self.scope:
            form["scope"] = self.scope
        if self.audience:
            form["audience"] = self.audience
        if self.grant_type == "password":
            form["username"] = self.username
            form["password"] = self.password
        if self.client_auth == "body":
            form["client_id"] = self.client_id
            if self.client_secret is not None:
                form["client_secret"] = self.client_secret
        form.update(self.extra_params)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if self.client_auth == "basic" and self.client_secret is not None:
            credentials = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(credentials).decode('ascii')}"

        request = Request(
            url=self.token_url,
            data=urlencode(form).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        text = self._send_token_request(request)
        return self._parse_token_response(text)

    def _send_token_request(self, request: Request) -> str:
        if self._opener is None:
            raise RuntimeError("OAuth2 token provider is closed.")

        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset("utf-8")
                return response.read().decode(charset)
        except HTTPError as exc:
            charset = exc.headers.get_content_charset("utf-8") if exc.headers else "utf-8"
            text = exc.read().decode(charset)
            raise HttpRequestError(
                f"OAuth2 token request failed with HTTP {exc.code} for {self.token_url}.",
                status_code=exc.code,
                url=exc.geturl(),
                payload=self._parse_optional_json(text),
            ) from exc
        except URLError as exc:
            raise HttpTransportError(
                f"OAuth2 token request failed for {self.token_url}: {exc.reason}"
            ) from exc

    def _parse_token_response(self, text: str) -> tuple[str, float | None]:
        payload = self._parse_optional_json(text)
        if not isinstance(payload, dict):
            raise ApiResponseError(
                f"Expected a JSON object token response from {self.token_url}."
            )

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ApiResponseError(
                f"OAuth2 token response from {self.token_url} did not include 'access_token'."
            )

        expires_in = payload.get("expires_in")
        if expires_in is None:
            return access_token, None
        try:
            seconds = float(expires_in)
        except (TypeError, ValueError) as exc:
            raise ApiResponseError(
                f"OAuth2 token response from {self.token_url} included an invalid 'expires_in'."
            ) from exc
        return access_token, time.monotonic() + max(seconds - self.leeway, 0.0)

    @staticmethod
    def _parse_optional_json(text: str) -> Any:
        if not text:
            return None
        try:
            return json.loads(text)
        except JSONDecodeError:
            return text


class OAuth2AuthHandler(AuthHandler, AbstractBasicAuthHandler):
    """Bearer token handler backed by an :class:`OAuth2Token` provider.

    The current access token is sent preemptively. When the API answers with
    ``401 Unauthorized`` the cached token is invalidated, a new token is
    requested and the original request is retried once through
    :meth:`AbstractBasicAuthHandler.retry_http_basic_auth`.
    """

    auth_header = "Authorization"

    def __init__(self, token: OAuth2Token | Mapping[str, Any]) -> None:
        if isinstance(token, Mapping):
            token = OAuth2Token.from_mapping(token)
        if not isinstance(token, OAuth2Token):
            raise TypeError(
                "token must be an OAuth2Token or a mapping of OAuth2Token arguments."
            )
        AuthHandler.__init__(self, password_mgr=HTTPPasswordMgr())
        self._token = token

    def http_request(self, request: Request) -> Request:
        if not request.has_header(self.auth_header):
            request.add_unredirected_header(
                self.auth_header,
                self._token.authorization_header,
            )
            request.oauth2_token_applied = True
        return request

    https_request = http_request

    def http_error_401(self, req, fp, code, msg, headers):
        host = urlparse(req.full_url)[1]
        return self.http_error_auth_reqed("www-authenticate", host, req, headers)

    def http_error_auth_reqed(self, authreq, host, req, headers):
        if not getattr(req, "oauth2_token_applied", False):
            return None
        if getattr(req, "oauth2_retried", False):
            return None
        self._token.invalidate()
        req.oauth2_retried = True
        return self.retry_http_basic_auth(host, req, None)

    def retry_http_basic_auth(self, host, req, realm):
        authorization = self._token.authorization_header
        if req.get_header(self.auth_header) == authorization:
            return None
        req.add_unredirected_header(self.auth_header, authorization)
        return self.parent.open(req, timeout=req.timeout)
