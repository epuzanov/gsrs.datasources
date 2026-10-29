"""GSRS ``auth-token`` header authentication."""

from __future__ import annotations

from collections.abc import Callable
from urllib.request import HTTPPasswordMgr, Request

from .base import AuthHandler
from .tokens import DEFAULT_TOKEN_TIME_RESOLUTION_MS, compute_gsrs_token

__all__ = [
    "ComputedTokenAuthHandler",
    "TokenAuthHandler",
]


class TokenAuthHandler(AuthHandler):
    """GSRS token authentication via the ``auth-token`` header.

    ``token`` is either a static token or a zero argument callable returning
    the token to send, which allows short lived tokens to be refreshed for
    every request.
    """

    header = "auth-token"

    def __init__(
        self,
        token: str | Callable[[], str],
        *,
        header: str | None = None,
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        super().__init__(password_mgr=password_mgr)
        if not callable(token) and not isinstance(token, str):
            raise TypeError("token must be a string or a zero argument callable.")
        if header is not None:
            if not header:
                raise ValueError("header must not be empty.")
            self.header = header
        self._token = token

    @property
    def token(self) -> str:
        value = self._token() if callable(self._token) else self._token
        if not value:
            raise ValueError("A GSRS token value is required.")
        return value

    def _build_headers(self, request: Request) -> dict[str, str]:
        return {self.header: self.token}


class ComputedTokenAuthHandler(TokenAuthHandler):
    """GSRS token authentication that derives the token from a user API key."""

    def __init__(
        self,
        username: str,
        key: str,
        *,
        time_resolution_ms: int = DEFAULT_TOKEN_TIME_RESOLUTION_MS,
        header: str | None = None,
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        if not username:
            raise ValueError("username must not be empty.")
        if not key:
            raise ValueError("key must not be empty.")
        if time_resolution_ms <= 0:
            raise ValueError("time_resolution_ms must be a positive integer.")
        self.username = username
        self.key = key
        self.time_resolution_ms = time_resolution_ms
        super().__init__(
            self._compute_token,
            header=header,
            password_mgr=password_mgr,
        )

    def _compute_token(self) -> str:
        return compute_gsrs_token(
            self.username,
            self.key,
            time_resolution_ms=self.time_resolution_ms,
        )
