"""Response containers produced by the HTTP layer and the GSRS API.

Two kinds of models live here:

* :class:`HttpResponse` (in :mod:`gsrs.responses.http`) is the plain transport
  response returned by :class:`gsrs.datasources.http.UrlLibSession`.
* The pydantic models for GSRS API payloads: :mod:`gsrs.responses.whoami` and
  :mod:`gsrs.responses.validation`.
"""

from __future__ import annotations

from .http import HttpResponse
from .validation import ValidationLink, ValidationMessage, ValidationResponse
from .whoami import WhoAmIGroup, WhoAmIResponse, WhoAmIRole, WhoAmIUser

__all__ = [
    "HttpResponse",
    "ValidationLink",
    "ValidationMessage",
    "ValidationResponse",
    "WhoAmIGroup",
    "WhoAmIResponse",
    "WhoAmIRole",
    "WhoAmIUser",
]
