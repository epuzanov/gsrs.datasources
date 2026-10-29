"""HTTP Basic and GSRS legacy username/password authentication."""

from __future__ import annotations

import base64
from urllib.request import Request

from .base import _CredentialAuthHandler

__all__ = [
    "BasicAuthHandler",
    "LegacyAuthHandler",
]


class BasicAuthHandler(_CredentialAuthHandler):
    """Preemptive HTTP Basic authentication handler backed by HTTPPasswordMgr."""

    def _build_headers(self, request: Request) -> dict[str, str]:
        username, password = self._credentials(request)
        if username is None and password is None:
            return {}
        credentials = f"{username}:{password}".encode("utf-8")
        token = base64.b64encode(credentials).decode("ascii")
        return {"Authorization": f"Basic {token}"}


class LegacyAuthHandler(_CredentialAuthHandler):
    """GSRS legacy authentication headers backed by HTTPPasswordMgr."""

    def _build_headers(self, request: Request) -> dict[str, str]:
        username, password = self._credentials(request)
        if username is None and password is None:
            return {}
        return {
            "auth-username": username,
            "auth-password": password,
        }
