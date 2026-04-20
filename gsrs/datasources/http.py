from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import OpenerDirector, Request, build_opener

from .base import Base
from .exceptions import ApiResponseError, DatasourceError, HttpRequestError, HttpTransportError


@dataclass
class HttpResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    text: str


class UrlLibSession:
    """Small stdlib-backed session wrapper with default headers and auth."""

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        auth: str | tuple[str, str] | None = None,
        legacy_auth: tuple[str, str] | None = None,
        opener: OpenerDirector | None = None,
    ) -> None:
        self._headers = dict(headers or {})
        self._auth_header = self._build_auth_header(auth)
        self._legacy_auth_headers = self._build_legacy_auth_headers(legacy_auth)
        self._opener = opener or build_opener()
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
        json_body: Any = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        if self._closed:
            raise RuntimeError("HTTP session is closed.")

        request_headers = dict(self._headers)
        if self._auth_header and "Authorization" not in request_headers:
            request_headers["Authorization"] = self._auth_header
        for key, value in self._legacy_auth_headers.items():
            request_headers.setdefault(key, value)
        if headers:
            request_headers.update(headers)

        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = Request(url=url, data=data, headers=request_headers, method=method.upper())

        try:
            with self._opener.open(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset("utf-8")
                return HttpResponse(
                    status_code=getattr(response, "status", response.getcode()),
                    url=response.geturl(),
                    headers=dict(response.headers.items()),
                    text=response.read().decode(charset),
                )
        except HTTPError as exc:
            charset = exc.headers.get_content_charset("utf-8") if exc.headers else "utf-8"
            return HttpResponse(
                status_code=exc.code,
                url=exc.geturl(),
                headers=dict(exc.headers.items()) if exc.headers else {},
                text=exc.read().decode(charset),
            )
        except URLError as exc:
            raise HttpTransportError(f"HTTP request failed for {url}: {exc.reason}") from exc

    @staticmethod
    def _build_auth_header(auth: str | tuple[str, str] | None) -> str | None:
        if auth is None:
            return None
        if isinstance(auth, str):
            return auth
        username, password = auth
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    @staticmethod
    def _build_legacy_auth_headers(
        legacy_auth: tuple[str, str] | None,
    ) -> dict[str, str]:
        if legacy_auth is None:
            return {}
        username, password = legacy_auth
        return {
            "auth-username": username,
            "auth-password": password,
        }


class Http(Base):
    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str] | None = None,
        auth: str | tuple[str, str] | None = None,
        legacy_auth: tuple[str, str] | None = None,
        timeout: float = 30.0,
        session: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or UrlLibSession(headers=headers, auth=auth, legacy_auth=legacy_auth)
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
        json_body: Any = None,
    ) -> Any:
        if self._closed:
            raise DatasourceError("Datasource is closed.")

        response = self._request(method, path, params=params, headers=headers, json_body=json_body)
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
        json_body: Any = None,
    ) -> HttpResponse:
        url = self._build_url(path, params=params)
        try:
            return self._session.request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                timeout=self.timeout,
            )
        except HttpTransportError:
            raise
        except Exception as exc:
            raise HttpTransportError(f"HTTP request failed for {url}: {exc}") from exc

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

    def _paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int = 50,
    ):
        current_path = path
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

            if total is not None:
                current_skip = int(current_params.get("skip", 0))
                if current_skip + item_count >= total:
                    return None

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
        parsed_query = parse_qs(parsed.query, keep_blank_values=True)
        next_params = {
            key: values if len(values) > 1 else values[0] for key, values in parsed_query.items()
        }
        return next_path.lstrip("/"), next_params
