"""urllib handler implementations used by the transport layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.request import BaseHandler, ProxyHandler, Request

from .proxy import _host_matches_no_proxy


class _ProxyHandler(ProxyHandler):
    """Proxy handler that also honours an explicit ``no_proxy`` host list."""

    proxies: dict[str, str]

    def __init__(self, proxies: Mapping[str, str], no_proxy: Sequence[str] = ()) -> None:
        super().__init__(dict(proxies))
        self.no_proxy = tuple(no_proxy)

    def proxy_open(self, req: Request, proxy: str, type: str):
        if self.no_proxy and _host_matches_no_proxy(getattr(req, "host", None), self.no_proxy):
            return None
        return super().proxy_open(req, proxy, type)


class _DelegatingHandler(BaseHandler):
    """Route HTTP(S) requests through an externally supplied opener.

    A caller supplied opener owns its transport settings, so it is also
    responsible for its proxy configuration.
    """

    handler_order = 0

    def __init__(self, opener: Any) -> None:
        self._opener = opener

    def http_open(self, request: Request):
        return self._opener.open(request, timeout=getattr(request, "timeout", None))

    https_open = http_open
