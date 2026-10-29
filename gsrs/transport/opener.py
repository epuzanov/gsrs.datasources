"""Construction of configured :class:`~urllib.request.OpenerDirector` objects."""

from __future__ import annotations

from urllib.request import (
    BaseHandler,
    HTTPSHandler,
    OpenerDirector,
    build_opener,
    getproxies,
)

from .handlers import _ProxyHandler
from .proxy import NoProxyConfig, ProxyConfig, _normalize_no_proxy, _normalize_proxies
from .tls import _create_ssl_context


def _build_proxy_handler(
    *,
    proxy: ProxyConfig = None,
    no_proxy: NoProxyConfig = None,
) -> _ProxyHandler | None:
    """Build a proxy handler from the configured or environment proxies.

    When ``proxy`` is omitted the environment proxy settings (``http_proxy``,
    ``https_proxy``, ...) are used, matching urllib's default behaviour, so that
    ``no_proxy`` entries can also be honoured for them.
    """
    normalized_no_proxy = _normalize_no_proxy(no_proxy)
    if proxy is None:
        # ``getproxies`` reports the environment ``no_proxy`` list under the
        # ``no`` key; it is not a proxy scheme.
        proxies = _normalize_proxies(
            {scheme: url for scheme, url in getproxies().items() if scheme != "no"}
        )
    else:
        proxies = _normalize_proxies(proxy)
    if not proxies:
        return None
    return _ProxyHandler(proxies, normalized_no_proxy)


def _build_url_opener(
    *handlers: BaseHandler,
    verify_ssl: bool = True,
    proxy: ProxyConfig = None,
    no_proxy: NoProxyConfig = None,
) -> OpenerDirector:
    """Build an opener with optional TLS and proxy configuration."""
    proxy_handler = _build_proxy_handler(proxy=proxy, no_proxy=no_proxy)
    builtin_handlers: list[BaseHandler] = list(handlers)
    if proxy_handler is not None:
        builtin_handlers.insert(0, proxy_handler)

    context = _create_ssl_context(verify_ssl=verify_ssl)
    if context is None:
        return build_opener(*builtin_handlers)
    return build_opener(*builtin_handlers, HTTPSHandler(context=context))
