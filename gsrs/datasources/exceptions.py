from __future__ import annotations

from typing import Any


class DatasourceError(Exception):
    """Base exception for datasource errors."""


class ResourceTypeError(ValueError):
    """Raised when an unsupported logical resource type is requested."""


class HttpTransportError(DatasourceError):
    """Raised when an HTTP request cannot be completed."""


class HttpRequestError(DatasourceError):
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


class ApiResponseError(DatasourceError):
    """Raised when the API responds with an unexpected payload."""
