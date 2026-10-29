"""GSRS ``ix.session`` cookie authentication."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.request import HTTPPasswordMgr, Request

from .base import AuthHandler

__all__ = [
    "DEFAULT_SESSION_COOKIE_NAME",
    "SessionCookieAuthHandler",
]

#: Cookie name used by GSRS for server side sessions.
DEFAULT_SESSION_COOKIE_NAME = "ix.session"


class SessionCookieAuthHandler(AuthHandler):
    """GSRS session authentication using the ``ix.session`` cookie.

    Pass a known ``session_id`` to authenticate immediately. When it is omitted
    the handler captures the cookie from the ``Set-Cookie`` response header of
    the first request that creates a session. Because a server only creates a
    session for an already authenticated request, pass ``credentials`` (for
    example a :class:`~gsrs.auth.LegacyAuthHandler`) to log in with:

    ```python
    auth = SessionCookieAuthHandler(credentials=LegacyAuthHandler("user", "secret"))
    ```

    Once the cookie is captured the credentials keep being sent, so GSRS falls
    back to them automatically when the stored session has expired.
    """

    def __init__(
        self,
        session_id: str | None = None,
        *,
        credentials: AuthHandler | None = None,
        cookie_name: str = DEFAULT_SESSION_COOKIE_NAME,
        capture: bool = True,
        header: str = "Cookie",
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        super().__init__(password_mgr=password_mgr)
        if not cookie_name:
            raise ValueError("cookie_name must not be empty.")
        if not header:
            raise ValueError("header must not be empty.")
        if credentials is not None and not isinstance(credentials, AuthHandler):
            raise TypeError("credentials must be an AuthHandler instance.")
        self.cookie_name = cookie_name
        self.capture = capture
        self.header = header
        self.session_id = session_id
        self.credentials = credentials

    def _build_headers(self, request: Request) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.credentials is not None:
            headers.update(self.credentials._build_headers(request))
        if self.session_id:
            headers[self.header] = f"{self.cookie_name}={self.session_id}"
        return headers

    def store_cookies(self, cookies: Mapping[str, str]) -> None:
        if not self.capture or self.session_id:
            return
        value = cookies.get(self.cookie_name)
        if value:
            self.session_id = value
