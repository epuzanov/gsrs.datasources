"""Exception hierarchy shared by the client packages.

This module is a dependency-free leaf: it imports nothing from the rest of the
package so that every other module -- ``gsrs.transport``, ``gsrs.responses``,
``gsrs.auth`` and ``gsrs.client`` -- can depend on it without creating an
import cycle.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ApiResponseError",
    "ClientError",
    "HttpRequestError",
    "HttpTransportError",
    "ResourceTypeError",
]


class ClientError(Exception):
    """Base exception for client errors."""


class ResourceTypeError(ValueError):
    """Raised when an unsupported logical resource type is requested."""


class HttpTransportError(ClientError):
    """Raised when an HTTP request cannot be completed."""


class HttpRequestError(ClientError):
    """Raised when an HTTP request returns an error response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.payload = payload


class ApiResponseError(ClientError):
    """Raised when the API responds with an unexpected payload."""
