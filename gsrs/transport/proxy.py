"""Proxy and ``no_proxy`` configuration for the urllib transport layer.

The public annotations (:data:`ProxyConfig`, :data:`NoProxyConfig`) live here so
callers can type proxy arguments without importing the opener machinery.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "DEFAULT_PROXY_SCHEMES",
    "NoProxyConfig",
    "ProxyConfig",
]

ProxyConfig = str | Mapping[str, str] | None
NoProxyConfig = str | Sequence[str] | None

#: Proxy schemes configured when a single proxy URL is supplied.
DEFAULT_PROXY_SCHEMES = ("http", "https")
#: Mapping keys that expand to :data:`DEFAULT_PROXY_SCHEMES`.
_PROXY_SCHEME_ALIASES = {"all": DEFAULT_PROXY_SCHEMES, "*": DEFAULT_PROXY_SCHEMES}


def _normalize_proxy_url(value: Any) -> str:
    """Return a proxy URL with an explicit scheme."""
    if not isinstance(value, str):
        raise TypeError("Proxy URLs must be strings.")
    url = value.strip()
    if not url:
        raise ValueError("Proxy URL must not be empty.")
    if "://" not in url:
        url = f"http://{url}"
    return url


def _normalize_proxies(proxy: ProxyConfig) -> dict[str, str] | None:
    """Normalize a proxy URL or scheme mapping into urllib's mapping form."""
    if proxy is None:
        return None
    if isinstance(proxy, str):
        url = _normalize_proxy_url(proxy)
        return {scheme: url for scheme in DEFAULT_PROXY_SCHEMES}
    if isinstance(proxy, Mapping):
        proxies: dict[str, str] = {}
        aliases: list[tuple[str, str]] = []
        for key, value in proxy.items():
            if not isinstance(key, str):
                raise TypeError(
                    "Proxy mapping keys must be strings such as 'http' or 'https'."
                )
            scheme = key.strip().lower().removesuffix("://").rstrip(":")
            if not scheme:
                raise ValueError("Proxy mapping keys must not be empty.")
            url = _normalize_proxy_url(value)
            if scheme in _PROXY_SCHEME_ALIASES:
                aliases.append((scheme, url))
            else:
                proxies[scheme] = url
        # Aliases only fill in schemes that were not configured explicitly.
        for scheme, url in aliases:
            for expanded_scheme in _PROXY_SCHEME_ALIASES[scheme]:
                proxies.setdefault(expanded_scheme, url)
        return proxies or None
    raise TypeError("proxy must be a proxy URL string or a mapping of scheme to proxy URL.")


def _normalize_no_proxy(no_proxy: NoProxyConfig) -> tuple[str, ...]:
    """Normalize ``no_proxy`` into a tuple of lowercase host patterns."""
    if no_proxy is None:
        return ()
    if isinstance(no_proxy, str):
        entries: Sequence[Any] = no_proxy.split(",")
    elif isinstance(no_proxy, Sequence):
        entries = no_proxy
    else:
        raise TypeError(
            "no_proxy must be a comma separated string or a sequence of host strings."
        )
    return tuple(
        normalized
        for normalized in (str(entry).strip().lower() for entry in entries)
        if normalized
    )


def _strip_host_port(entry: str) -> str:
    """Return a ``no_proxy`` entry without an optional port."""
    if entry.startswith("["):
        end = entry.find("]")
        return entry[1:end] if end != -1 else entry
    if entry.count(":") == 1:
        host, _, port = entry.partition(":")
        if port.isdigit():
            return host
    return entry


def _host_matches_no_proxy(host: str | None, no_proxy: Sequence[str]) -> bool:
    """Return ``True`` when ``host`` is covered by one of the ``no_proxy`` patterns."""
    if not host or not no_proxy:
        return False
    hostname = (urlparse(f"//{host}").hostname or host).lower().rstrip(".")

    for entry in no_proxy:
        if entry == "*":
            return True
        # Entries are matched against the host itself and its subdomains, so both
        # "example.test" and ".example.test" cover "api.example.test".
        candidate = _strip_host_port(entry.lstrip("*").lstrip(".")).rstrip(".")
        if not candidate:
            continue
        if hostname == candidate or hostname.endswith(f".{candidate}"):
            return True
    return False
