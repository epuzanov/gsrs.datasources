"""The plain HTTP response container.

:class:`HttpResponse` is transport-level: it carries status, URL, headers, body
text, and the cookies parsed from ``Set-Cookie``. It has no dependency on
pydantic, so the session layer can import it without pulling in the API models.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["HttpResponse"]


@dataclass
class HttpResponse:
    """Decoded HTTP response, including cookies captured from ``Set-Cookie``."""

    status_code: int
    url: str
    headers: dict[str, str]
    text: str
    cookies: dict[str, str] = field(default_factory=dict)
