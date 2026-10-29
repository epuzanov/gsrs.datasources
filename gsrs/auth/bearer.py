"""Static OAuth2 bearer token authentication."""

from __future__ import annotations

from urllib.request import HTTPPasswordMgr, Request

from .base import AuthHandler

__all__ = ["BearerAuthHandler"]


class BearerAuthHandler(AuthHandler):
    """Static OAuth2 bearer token authentication handler."""

    def __init__(
        self,
        token: str,
        *,
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        super().__init__(password_mgr=password_mgr)
        self._token = token

    def http_request(self, request: Request) -> Request:
        if not request.has_header("Authorization"):
            request.add_unredirected_header(
                "Authorization",
                f"Bearer {self._token}",
            )
        return request

    https_request = http_request
