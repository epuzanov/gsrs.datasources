"""Helpers for reading response headers.

urllib exposes headers through different objects depending on whether a request
succeeded or was answered with an error, so these helpers normalize both shapes.
"""

from __future__ import annotations

from typing import Any


def _header_values(headers: Any, name: str) -> list[str]:
    """Return every value of ``name`` from an HTTP header mapping."""
    if headers is None:
        return []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values: Any = get_all(name) or []
        return [value for value in values if value]
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(item) for item in value]


def _parse_set_cookie_headers(headers: Any) -> dict[str, str]:
    """Parse ``Set-Cookie`` response headers into a name to value mapping."""
    cookies: dict[str, str] = {}
    for header in _header_values(headers, "Set-Cookie"):
        name, separator, value = header.partition("=")
        if not separator:
            continue
        cookie_name = name.strip()
        if not cookie_name:
            continue
        cookies[cookie_name] = value.split(";", 1)[0].strip()
    return cookies
