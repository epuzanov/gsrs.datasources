"""Proxy, TLS, and opener plumbing shared by the HTTP layers.

This is the lowest layer of the HTTP stack. It is split by concern:

* :mod:`gsrs.transport.proxy` - proxy/``no_proxy`` configuration and matching.
* :mod:`gsrs.transport.tls` - SSL context creation.
* :mod:`gsrs.transport.headers` - response header helpers.
* :mod:`gsrs.transport.handlers` - urllib handler implementations.
* :mod:`gsrs.transport.opener` - opener construction.

Nothing here depends on authentication or on the client classes, so both
:mod:`gsrs.auth` and :mod:`gsrs.client.http` can import it without creating
a cycle.
"""

from __future__ import annotations

# The private helpers below belong to this layer, but they are re-exported so
# sibling modules (``gsrs.auth.oauth2``, ``gsrs.client.http``) can import
# the transport surface from one place. ``noqa: F401`` marks the re-exports as
# intentional.
from .handlers import (  # noqa: F401
    _DelegatingHandler,
    _ProxyHandler,
)
from .headers import (  # noqa: F401
    _header_values,
    _parse_set_cookie_headers,
)
from .opener import (  # noqa: F401
    _build_proxy_handler,
    _build_url_opener,
)
from .proxy import (  # noqa: F401
    DEFAULT_PROXY_SCHEMES,
    NoProxyConfig,
    ProxyConfig,
    _host_matches_no_proxy,
    _normalize_no_proxy,
    _normalize_proxies,
    _normalize_proxy_url,
    _strip_host_port,
)
from .tls import _create_ssl_context  # noqa: F401

__all__ = [
    "DEFAULT_PROXY_SCHEMES",
    "NoProxyConfig",
    "ProxyConfig",
]
