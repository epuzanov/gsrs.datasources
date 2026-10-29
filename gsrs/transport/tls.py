"""TLS configuration for the urllib transport layer."""

from __future__ import annotations

import ssl


def _create_ssl_context(*, verify_ssl: bool) -> ssl.SSLContext | None:
    """Return a permissive SSL context when certificate verification is disabled."""
    if verify_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
