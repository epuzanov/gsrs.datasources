"""GSRS computed token derivation."""

from __future__ import annotations

import hashlib
import time

__all__ = [
    "DEFAULT_TOKEN_TIME_RESOLUTION_MS",
    "compute_gsrs_token",
]

#: Default canonical timestamp resolution used by GSRS computed tokens (one day).
DEFAULT_TOKEN_TIME_RESOLUTION_MS = 86400000


def _current_time_millis() -> int:
    return int(time.time() * 1000)


def compute_gsrs_token(
    username: str,
    key: str,
    *,
    time_resolution_ms: int = DEFAULT_TOKEN_TIME_RESOLUTION_MS,
    timestamp_ms: int | None = None,
) -> str:
    """Compute a GSRS token from a username and API key.

    GSRS does not store tokens: the server derives them with
    ``sha1(canonicalTimestamp + username + key)`` where ``canonicalTimestamp``
    is the clock truncated to ``gsrs.tokens.timeResolutionMS``. The same value
    is exposed as ``computedToken`` (and the API key as ``key``) by
    ``api/v1/whoami``.
    """
    if not username:
        raise ValueError("username must not be empty.")
    if not key:
        raise ValueError("key must not be empty.")
    if time_resolution_ms <= 0:
        raise ValueError("time_resolution_ms must be a positive integer.")
    current = _current_time_millis() if timestamp_ms is None else timestamp_ms
    canonical_timestamp = int(current // time_resolution_ms)
    payload = f"{canonical_timestamp}{username}{key}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()
