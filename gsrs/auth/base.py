"""The handler base class shared by every authentication mode."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse
from urllib.request import BaseHandler, HTTPPasswordMgr, Request

__all__ = ["AuthHandler"]


def _request_origin(url: str) -> str:
    """Return the ``scheme://host`` part of ``url``."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}"


class AuthHandler(BaseHandler):
    """Authentication handler that injects headers into HTTP requests.

    Credentials are kept in an :class:`~urllib.request.HTTPPasswordMgr` so all
    authentication modes share urllib's credential lookup mechanism.
    """

    handler_order = 400

    def __init__(
        self,
        headers: Mapping[str, str] | None = None,
        *,
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        self._headers = dict(headers or {})
        self.passwd = password_mgr or HTTPPasswordMgr()

    def add_password(
        self,
        realm: str | None,
        uri: Any,
        username: str,
        password: str,
    ) -> None:
        self.passwd.add_password(realm, uri, username, password)

    def http_request(self, request: Request) -> Request:
        for name, value in self._build_headers(request).items():
            if not request.has_header(name):
                request.add_unredirected_header(name, value)
        return request

    https_request = http_request

    def _build_headers(self, request: Request) -> dict[str, str]:
        return dict(self._headers)


class _CredentialAuthHandler(AuthHandler):
    """Auth handler whose credentials are resolved through HTTPPasswordMgr."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        super().__init__(password_mgr=password_mgr)
        self._username = username
        self._password = password
        self._registered_origins: set[str] = set()

    def _credentials(self, request: Request) -> tuple[str | None, str | None]:
        origin = _request_origin(request.full_url)
        if origin not in self._registered_origins:
            self.add_password(None, origin, self._username, self._password)
            self._registered_origins.add(origin)
        return self.passwd.find_user_password(None, request.full_url)
