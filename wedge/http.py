"""Shared async HTTP client with pooling, timeouts, and retry/backoff."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx

DEFAULT_TIMEOUT = 10.0
MAX_RETRIES = 3
BACKOFF_BASE = 0.5  # seconds; doubles each retry


def make_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """Create a pooled AsyncClient. Caller is responsible for closing it."""
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    return httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers={"User-Agent": "wedge/0.1 (weather-edge-scanner)"},
        follow_redirects=True,
    )


@asynccontextmanager
async def client_session(timeout: float = DEFAULT_TIMEOUT) -> AsyncIterator[httpx.AsyncClient]:
    """Async context manager yielding a pooled client that auto-closes."""
    client = make_client(timeout)
    try:
        yield client
    finally:
        await client.aclose()


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """GET a URL and return parsed JSON, retrying transient failures with backoff.

    Raises httpx.HTTPStatusError on a final non-retryable failure so callers can
    distinguish 404 (skip) from other errors.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params)
            # Retry on 429 / 5xx; surface 4xx (e.g. 404) immediately.
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # Don't retry definitive client errors other than rate limiting.
            if status is not None and 400 <= status < 500 and status != 429:
                raise
            last_exc = exc
            if attempt < retries - 1:
                await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
    assert last_exc is not None
    raise last_exc
