"""GSRS trust-header (SSO proxy) authentication."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.request import HTTPPasswordMgr, Request

from .base import AuthHandler

__all__ = ["SsoHeaderAuthHandler"]


class SsoHeaderAuthHandler(AuthHandler):
    """GSRS trust header (SSO proxy) authentication.

    The ``ix.authentication.trustheader`` mode expects an upstream single sign
    on proxy to supply the user name (and optionally e-mail and roles) in
    configured headers, for example ``OAM_REMOTE_USER``.
    """

    def __init__(
        self,
        username: str,
        *,
        username_header: str = "OAM_REMOTE_USER",
        email: str | None = None,
        email_header: str | None = None,
        roles: Sequence[str] | str | None = None,
        roles_header: str | None = None,
        roles_separator: str = ";",
        password_mgr: HTTPPasswordMgr | None = None,
    ) -> None:
        super().__init__(password_mgr=password_mgr)
        if not username:
            raise ValueError("username must not be empty.")
        if not username_header:
            raise ValueError("username_header must not be empty.")
        if email is not None and not email_header:
            raise ValueError("email_header is required when email is set.")
        if roles is not None and not roles_header:
            raise ValueError("roles_header is required when roles are set.")
        self.username = username
        self.username_header = username_header
        self.email = email
        self.email_header = email_header
        self.roles = roles
        self.roles_header = roles_header
        self.roles_separator = roles_separator

    def _build_headers(self, request: Request) -> dict[str, str]:
        headers = {self.username_header: self.username}
        if self.email is not None and self.email_header:
            headers[self.email_header] = self.email
        if self.roles is not None and self.roles_header:
            if isinstance(self.roles, str):
                headers[self.roles_header] = self.roles
            else:
                headers[self.roles_header] = self.roles_separator.join(self.roles)
        return headers
