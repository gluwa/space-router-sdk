"""Response models for the SpaceRouter SDK."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Routing & filtering types
# ---------------------------------------------------------------------------

IpType = Literal["residential", "mobile", "datacenter", "business"]
"""IP address type for filtering proxy nodes."""

NodeStatus = Literal["offline", "draining"]
"""Node operational status (for status updates). Nodes go online via health probes."""

NodeConnectivityType = Literal["direct", "upnp", "external_provider"]
"""How a node connects to the network."""

# ---------------------------------------------------------------------------
# API key models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Node management models
# ---------------------------------------------------------------------------


class Node(BaseModel):
    """Proxy node returned by ``GET /nodes`` and ``POST /nodes``."""

    id: str
    endpoint_url: str
    public_ip: str
    connectivity_type: str
    node_type: str
    status: str
    health_score: float
    region: str
    label: str | None = None
    ip_type: str
    ip_region: str
    as_type: str
    wallet_address: str
    created_at: str
    gateway_ca_cert: str | None = None


# ---------------------------------------------------------------------------
# Staking registration models
# ---------------------------------------------------------------------------


class RegisterChallenge(BaseModel):
    """Challenge returned by ``POST /nodes/register/challenge``."""

    nonce: str
    expires_in: int


class RegisterResult(BaseModel):
    """Result of ``POST /nodes/register/verify``."""

    status: str
    node_id: str
    address: str
    endpoint_url: str
    gateway_ca_cert: str | None = None


# ---------------------------------------------------------------------------
# Billing models
# ---------------------------------------------------------------------------


class CheckoutSession(BaseModel):
    """Checkout session returned by ``POST /billing/checkout``."""

    checkout_url: str


class BillingReissueResult(BaseModel):
    """Reissued API key returned by ``POST /billing/reissue``."""

    new_api_key: str


# ---------------------------------------------------------------------------
# Dashboard models
# ---------------------------------------------------------------------------


class Transfer(BaseModel):
    """Single data transfer record."""

    request_id: str
    bytes: int
    method: str
    target_host: str
    created_at: str


class TransferPage(BaseModel):
    """Paginated transfer list from ``GET /dashboard/transfers``."""

    page: int
    total_pages: int
    total_bytes: int
    transfers: list[Transfer]


class ProxyResponse:
    """Thin wrapper around :class:`httpx.Response` with SpaceRouter metadata.

    Exposes ``node_id`` and ``request_id`` from response headers and
    delegates everything else to the underlying httpx response.
    """

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def request_id(self) -> str | None:
        """Unique request ID for tracing (``X-SpaceRouter-Request-Id``)."""
        return self._response.headers.get("x-spacerouter-request-id")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __repr__(self) -> str:
        return f"<ProxyResponse [{self._response.status_code}]>"
