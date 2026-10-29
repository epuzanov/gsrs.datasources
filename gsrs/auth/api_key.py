"""GSRS ``auth-key`` header authentication."""

from __future__ import annotations

from urllib.request import HTTPPasswordMgr, Request

from .base import AuthHandler

__all__ = ["ApiKeyAuthHandler"]


class ApiKeyAuthHandler(AuthHandler):
    """GSRS API key authentication via the ``auth-key`` header.

    GSRS resolves the API key against the user profile named by
    ``auth-username``. Some deployments read the legacy ``auth-user`` header
    instead, which can be selected with the ``user_header`` argument.
    """

    def __init__(
        self,
        key: str,
        *,
        username: str | None = None,
        key_header: str = "auth-key",
        user_header: str | None = "auth-username",
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        super().__init__(password_mgr=password_mgr)
        if not key:
            raise ValueError("key must not be empty.")
        if not key_header:
            raise ValueError("key_header must not be empty.")
        self.key = key
        self.username = username
        self.key_header = key_header
        self.user_header = user_header

    def _build_headers(self, request: Request) -> dict[str, str]:
        headers = {self.key_header: self.key}
        if self.username is not None and self.user_header:
            headers[self.user_header] = self.username
        return headers
