"""HTTP client base and urllib session wrapper.

This module is the top layer of the HTTP stack: :class:`UrlLibSession` sends
requests through an :class:`~urllib.request.OpenerDirector` and :class:`Http`
adds request and error helpers on top of it. Pagination is GSRS specific and
lives in :mod:`gsrs.client.gsrs`.

Proxy and TLS plumbing lives in :mod:`gsrs.transport`, the response containers
in :mod:`gsrs.responses`, and the authentication handlers and token provider in
:mod:`gsrs.auth`. Those names are re-exported here so existing imports such as
``from gsrs.client.http import AuthHandler`` keep working.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from urllib.request import Request

from pydantic import BaseModel

from gsrs.auth import (
    DEFAULT_SESSION_COOKIE_NAME,
    DEFAULT_TOKEN_TIME_RESOLUTION_MS,
    ApiKeyAuthHandler,
    AuthHandler,
    BasicAuthHandler,
    BearerAuthHandler,
    ComputedTokenAuthHandler,
    LegacyAuthHandler,
    OAuth2AuthHandler,
    OAuth2Token,
    SessionCookieAuthHandler,
    SsoHeaderAuthHandler,
    TokenAuthHandler,
    compute_gsrs_token,
)
from gsrs.exceptions import (
    ApiResponseError,
    ClientError,
    HttpRequestError,
    HttpTransportError,
    ResourceTypeError,
)
from gsrs.responses import HttpResponse
from gsrs.transport import (
    NoProxyConfig,
    ProxyConfig,
    _build_url_opener,
    _DelegatingHandler,
    _normalize_no_proxy,
    _normalize_proxies,
    _parse_set_cookie_headers,
)

from .base import Base

__all__ = [
    "DEFAULT_SESSION_COOKIE_NAME",
    "DEFAULT_TOKEN_TIME_RESOLUTION_MS",
    "ApiKeyAuthHandler",
    "AuthHandler",
    "BasicAuthHandler",
    "BearerAuthHandler",
    "ComputedTokenAuthHandler",
    "Http",
    "HttpResponse",
    "LegacyAuthHandler",
    "NoProxyConfig",
    "OAuth2AuthHandler",
    "OAuth2Token",
    "ProxyConfig",
    "SessionCookieAuthHandler",
    "SsoHeaderAuthHandler",
    "TokenAuthHandler",
    "UrlLibSession",
    "compute_gsrs_token",
]


class UrlLibSession:
    """Small stdlib-backed session wrapper with default headers and auth."""

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        auth: AuthHandler | None = None,
        verify_ssl: bool = True,
        proxy: ProxyConfig = None,
        no_proxy: NoProxyConfig = None,
        opener: Any = None,
    ) -> None:
        if auth is not None and not isinstance(auth, AuthHandler):
            raise TypeError("auth must be an AuthHandler instance.")

        self._headers = dict(headers or {})
        self._auth = auth
        self._auth_handlers = [auth] if auth is not None else []
        self.verify_ssl = verify_ssl
        self.proxy = _normalize_proxies(proxy)
        self.no_proxy = _normalize_no_proxy(no_proxy)
        if opener is None:
            self._opener = _build_url_opener(
                *self._auth_handlers,
                verify_ssl=verify_ssl,
                proxy=proxy,
                no_proxy=no_proxy,
            )
        else:
            # A caller supplied opener owns its transport configuration,
            # including proxies.
            self._opener = _build_url_opener(
                *self._auth_handlers,
                _DelegatingHandler(opener),
                verify_ssl=verify_ssl,
            )
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._opener = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        if self._closed:
            raise RuntimeError("HTTP session is closed.")

        request_headers = dict(self._headers)
        if headers:
            request_headers.update(headers)

        return self._send(
            method,
            url,
            data=data,
            headers=request_headers,
            timeout=timeout,
        )

    def _send(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None,
        headers: dict[str, str],
        timeout: float | None,
    ) -> HttpResponse:
        request = Request(url=url, data=data, headers=headers, method=method.upper())

        try:
            with self._opener.open(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset("utf-8")
                http_response = HttpResponse(
                    status_code=getattr(response, "status", response.getcode()),
                    url=response.geturl(),
                    headers=dict(response.headers.items()),
                    text=response.read().decode(charset),
                    cookies=_parse_set_cookie_headers(response.headers),
                )
                self._capture_cookies(http_response)
                return http_response
        except HTTPError as exc:
            charset = exc.headers.get_content_charset("utf-8") if exc.headers else "utf-8"
            http_response = HttpResponse(
                status_code=exc.code,
                url=exc.geturl(),
                headers=dict(exc.headers.items()) if exc.headers else {},
                text=exc.read().decode(charset),
                cookies=_parse_set_cookie_headers(exc.headers),
            )
            self._capture_cookies(http_response)
            return http_response
        except URLError as exc:
            raise HttpTransportError(f"HTTP request failed for {url}: {exc.reason}") from exc

    def _capture_cookies(self, response: HttpResponse) -> None:
        """Offer response cookies to the auth handler for session reuse."""
        store = getattr(self._auth, "store_cookies", None)
        if callable(store) and response.cookies:
            store(response.cookies)


class Http(Base):
    """Reusable HTTP client base built on the standard library.

    Requests are sent through :class:`UrlLibSession`. Set ``proxy`` to a proxy
    URL (or a mapping of scheme to proxy URL) to route them through a proxy,
    and ``no_proxy`` to list hosts that bypass it. Both settings are also
    honoured by :class:`OAuth2Token`.
    """

    def __init__(
        self,
        base_url: str,
        resource_type: type | None = None,
        headers: dict[str, str] | None = None,
        auth: AuthHandler | None = None,
        verify_ssl: bool = True,
        proxy: ProxyConfig = None,
        no_proxy: NoProxyConfig = None,
        timeout: float = 30.0,
        session: Any = None,
        **kwargs: Any,
    ) -> None:
        if auth is not None and not isinstance(auth, AuthHandler):
            raise TypeError("auth must be an AuthHandler instance.")
        super().__init__(resource_type=resource_type, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.verify_ssl = verify_ssl
        self.proxy = _normalize_proxies(proxy)
        self.no_proxy = _normalize_no_proxy(no_proxy)
        self.timeout = timeout
        self._session = session or UrlLibSession(
            headers=headers,
            auth=auth,
            verify_ssl=verify_ssl,
            proxy=proxy,
            no_proxy=no_proxy,
        )
        self._owns_session = session is None
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        if self._owns_session and hasattr(self._session, "close"):
            self._session.close()
        self._closed = True

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: bytes | BaseModel | dict[str, Any] | None = None,
    ) -> Any:
        if self._closed:
            raise ClientError("Client is closed.")

        response = self._request(method, path, params=params, headers=headers, data=data)
        if not 200 <= response.status_code < 300:
            self._raise_for_response(response)

        if not response.text:
            return None
        try:
            return json.loads(response.text)
        except JSONDecodeError as exc:
            raise ApiResponseError(f"Expected JSON response from {response.url}.") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: bytes | BaseModel | dict[str, Any] | None = None,
    ) -> HttpResponse:
        if isinstance(data, (BaseModel, dict)):
            data = self._serialize_object(data)
            headers = dict(headers or {})
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        url = self._build_url(path, params=params)
        try:
            return self._session.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=self.timeout,
            )
        except HttpTransportError:
            raise
        except Exception as exc:
            raise HttpTransportError(f"HTTP request failed for {url}: {exc}") from exc

    def _resource_url(self, *path_segments: str) -> str:
        """Join ``path_segments`` onto the resource path.

        Segments are stripped of surrounding slashes before being quoted, and
        empty segments are dropped, so ``_resource_url()`` yields the collection
        URL itself. ``resource_path`` is stored without a trailing slash (an
        empty one means raw mode), so the separator is added here. ``@`` is kept
        literal because GSRS operation endpoints are named ``@validate`` and
        ``@approve``.
        """
        base = (
            f"{self.base_url}/{self.resource_path}"
            if self.resource_path
            else self.base_url
        )
        parts = [
            quote(segment.strip("/"), safe="@")
            for segment in path_segments
            if segment.strip("/")
        ]
        if not parts:
            return base
        return f"{base}/{'/'.join(parts)}"

    def _build_url(self, path: str, *, params: dict[str, Any] | None = None) -> str:
        url = path if path.startswith("http://") or path.startswith("https://") else urljoin(
            f"{self.base_url}/", path.lstrip("/")
        )
        if not params:
            return url
        clean_params = {key: value for key, value in params.items() if value is not None}
        if not clean_params:
            return url
        query = urlencode(clean_params, doseq=True)
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{query}"

    def _raise_for_response(self, response: HttpResponse) -> None:
        payload = None
        if response.text:
            try:
                payload = json.loads(response.text)
            except JSONDecodeError:
                payload = response.text

        message = f"HTTP {response.status_code} returned for {response.url}."
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error") or payload.get("detail")
            if detail:
                message = f"{message} {detail}"
        raise HttpRequestError(
            message,
            status_code=response.status_code,
            url=response.url,
            payload=payload,
        )

    def _serialize_object(self, obj: BaseModel | dict[str, Any]) -> bytes | None:
        if isinstance(obj, Mapping):
            return json.dumps(dict(obj)).encode("utf-8")
        model_dump_json = getattr(obj, "model_dump_json", None)
        if callable(model_dump_json):
            return model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
        legacy_dict = getattr(obj, "dict", None)
        if callable(legacy_dict):
            return legacy_dict(by_alias=True, exclude_none=True).encode("utf-8")
        raise ResourceTypeError(f"Object of type {type(obj).__name__} cannot be serialized.")

    def _paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int = 50,
    ) -> Iterator[dict[str, Any]]:
        current_path: str | None = path
        current_params = dict(params or {})
        current_params.setdefault("top", page_size)
        current_params.setdefault("skip", 0)

        while current_path is not None:
            payload = self._request_json("GET", current_path, params=current_params)
            items = self._extract_page_items(payload)
            for item in items:
                yield item

            next_request = self._get_next_page_request(
                payload=payload,
                current_path=current_path,
                current_params=current_params,
                item_count=len(items),
            )
            if next_request is None:
                break
            current_path, current_params = next_request

    def _extract_page_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("content", "results", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        raise ApiResponseError("Expected a paginated JSON object with a list payload.")

    def _get_next_page_request(
        self,
        *,
        payload: Any,
        current_path: str,
        current_params: dict[str, Any],
        item_count: int,
    ) -> tuple[str, dict[str, Any]] | None:
        if item_count == 0:
            return None

        if isinstance(payload, dict):
            next_link = payload.get("nextPageUri") or payload.get("nextPageUrl") or payload.get("next")
            if isinstance(next_link, str) and next_link:
                return self._parse_next_link(next_link)

            total = None
            for key in ("total", "count", "totalResults", "totalElements"):
                value = payload.get(key)
                if isinstance(value, int):
                    total = value
                    break

            # An explicit total is authoritative: keep paging until it is
            # reached, even when the server returns a short page.
            if total is not None:
                current_skip = int(current_params.get("skip", 0))
                if current_skip + item_count >= total:
                    return None
            else:
                # Without a total, treat a short page as the last one.
                page_size = int(current_params.get("top", item_count))
                if item_count < page_size:
                    return None

        next_params = dict(current_params)
        next_params["skip"] = int(current_params.get("skip", 0)) + item_count
        return current_path, next_params

    def _parse_next_link(self, next_link: str) -> tuple[str, dict[str, Any]]:
        parsed = urlparse(next_link)
        base_path = urlparse(self.base_url).path.rstrip("/")
        next_path = parsed.path
        if base_path and next_path.startswith(base_path):
            next_path = next_path[len(base_path) :]
        elif base_path in next_path:
            next_path = next_path.split(base_path, 1)[-1]
        parsed_query = parse_qs(parsed.query, keep_blank_values=True)
        next_params = {
            key: values if len(values) > 1 else values[0] for key, values in parsed_query.items()
        }
        return next_path.lstrip("/"), next_params

