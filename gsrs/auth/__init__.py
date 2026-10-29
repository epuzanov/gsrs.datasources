"""Authentication handlers for the GSRS HTTP datasources.

Every supported authentication method is an :class:`AuthHandler` subclass that
injects the headers GSRS expects into outgoing requests. Handlers are built on
:class:`urllib.request.BaseHandler`, so they can be registered in any urllib
opener; :class:`gsrs.datasources.http.UrlLibSession` registers the ``auth``
handler it is given and reuses it for the whole session.

The package is split by authentication mode:

* :mod:`gsrs.auth.base` - :class:`AuthHandler` and the credential base class.
* :mod:`gsrs.auth.tokens` - GSRS computed token derivation.
* :mod:`gsrs.auth.basic` - HTTP Basic and GSRS legacy credentials.
* :mod:`gsrs.auth.token_header` - ``auth-token`` headers.
* :mod:`gsrs.auth.api_key` - ``auth-key`` headers.
* :mod:`gsrs.auth.sso` - trust headers.
* :mod:`gsrs.auth.session` - ``ix.session`` cookies.
* :mod:`gsrs.auth.bearer` - static bearer tokens.
* :mod:`gsrs.auth.oauth2` - :class:`OAuth2Token` and its bearer handler.
"""

from __future__ import annotations

from .api_key import ApiKeyAuthHandler
from .base import AuthHandler
from .basic import BasicAuthHandler, LegacyAuthHandler
from .bearer import BearerAuthHandler
from .oauth2 import OAuth2AuthHandler, OAuth2Token
from .session import DEFAULT_SESSION_COOKIE_NAME, SessionCookieAuthHandler
from .sso import SsoHeaderAuthHandler
from .token_header import ComputedTokenAuthHandler, TokenAuthHandler
from .tokens import DEFAULT_TOKEN_TIME_RESOLUTION_MS, compute_gsrs_token

__all__ = [
    "DEFAULT_SESSION_COOKIE_NAME",
    "DEFAULT_TOKEN_TIME_RESOLUTION_MS",
    "ApiKeyAuthHandler",
    "AuthHandler",
    "BasicAuthHandler",
    "BearerAuthHandler",
    "ComputedTokenAuthHandler",
    "LegacyAuthHandler",
    "OAuth2AuthHandler",
    "OAuth2Token",
    "SessionCookieAuthHandler",
    "SsoHeaderAuthHandler",
    "TokenAuthHandler",
    "compute_gsrs_token",
]
