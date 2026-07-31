"""Sikker TLS-konfigurasjon for virksomhetsstyrte Windows-maskiner."""

from __future__ import annotations

import threading

import truststore

_LOCK = threading.Lock()
_CONFIGURED = False


def configure_system_trust_store() -> None:
    """La HTTPS-klienter bruke operativsystemets administrerte sertifikatlager."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    with _LOCK:
        if not _CONFIGURED:
            truststore.inject_into_ssl()
            _CONFIGURED = True
