"""Response models for the SpaceRouter SDK."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel


class ApiKey(BaseModel):
    """API key returned at creation time (POST /api-keys).

    The raw ``api_key`` value is only available in this response.
    """

    id: str
    name: str
    api_key: str
    rate_limit_rpm: int


class ApiKeyInfo(BaseModel):
    """API key metadata returned by list endpoint (GET /api-keys).

    The raw key is never included — only ``key_prefix`` (first 12 chars).
    """

    id: str
    name: str
    key_prefix: str
    rate_limit_rpm: int
    is_active: bool
    created_at: str


class ProxyResponse:
    """Thin wrapper around :class:`httpx.Response` with SpaceRouter metadata.

    Exposes ``node_id`` and ``request_id`` from response headers and
    delegates everything else to the underlying httpx response.
    """

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def node_id(self) -> str | None:
        """Node that handled the request (``X-SpaceRouter-Node``)."""
        return self._response.headers.get("x-spacerouter-node")

    @property
    def request_id(self) -> str | None:
        """Unique request ID for tracing (``X-SpaceRouter-Request-Id``)."""
        return self._response.headers.get("x-spacerouter-request-id")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __repr__(self) -> str:
        return f"<ProxyResponse [{self._response.status_code}]>"
