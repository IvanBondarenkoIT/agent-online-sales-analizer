"""Shared HTTP client helpers."""

from __future__ import annotations

import httpx

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


def create_http_client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(timeout=timeout)
