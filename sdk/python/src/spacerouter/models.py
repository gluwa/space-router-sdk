"""Response models for the SpaceRouter SDK."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, computed_field, model_validator

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
    """Proxy node returned by ``GET /nodes`` and ``POST /nodes``.

    v0.2.0 uses three role-specific wallet addresses.  The legacy
    ``wallet_address`` field is kept as a computed alias that returns
    ``identity_address`` for backward compatibility.
    """

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
    identity_address: str
    staking_address: str
    collection_address: str
    created_at: str
    gateway_ca_cert: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def wallet_address(self) -> str:
        """Backward-compatible alias — returns ``identity_address``."""
        return self.identity_address

    @model_validator(mode="before")
    @classmethod
    def _migrate_wallet_address(cls, data: Any) -> Any:
        """Accept legacy payloads that only contain ``wallet_address``."""
        if isinstance(data, dict) and "wallet_address" in data:
            for field in ("identity_address", "staking_address", "collection_address"):
                data.setdefault(field, data["wallet_address"])
        return data


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
    identity_address: str
    staking_address: str
    collection_address: str
    endpoint_url: str
    gateway_ca_cert: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def address(self) -> str:
        """Backward-compatible alias — returns ``identity_address``."""
        return self.identity_address

    @model_validator(mode="before")
    @classmethod
    def _migrate_address(cls, data: Any) -> Any:
        """Accept legacy payloads that only contain ``address``."""
        if isinstance(data, dict) and "address" in data:
            data.setdefault("identity_address", data["address"])
            data.setdefault("staking_address", data.get("identity_address", data["address"]))
            data.setdefault("collection_address", data.get("identity_address", data["address"]))
        return data


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


# ---------------------------------------------------------------------------
# Credit line models (v0.2.0)
# ---------------------------------------------------------------------------

CreditLineStatusType = Literal["active", "suspended", "pending"]


class CreditLineStatus(BaseModel):
    """Credit line status from ``GET /credit-lines/{address}``."""

    address: str
    credit_limit: float
    used: float
    available: float
    status: CreditLineStatusType
    foundation_managed: bool


class VouchingSignature(BaseModel):
    """Vouching signature proving identity wallet vouches for staking wallet."""

    identity_address: str
    staking_address: str
    signature: str
    timestamp: int


class ProxyResponse:
    """Thin wrapper around :class:`httpx.Response` with SpaceRouter metadata.

    Exposes ``request_id`` from response headers and delegates everything
    else to the underlying httpx response.

    HTTPS targets — known limitation
    --------------------------------
    For HTTP target URLs the gateway injects ``X-SpaceRouter-Request-Id``
    into the inner response and ``request_id`` works as expected. For
    HTTPS target URLs the gateway only sees the proxy ``CONNECT`` (the
    inner request is end-to-end TLS), so it can only stamp the request
    ID on the ``CONNECT 200`` response — and httpx does not surface
    ``CONNECT`` response headers to callers. As a result,
    ``request_id`` is ``None`` for HTTPS targets in the Python SDK
    today. The gateway-side ID still exists and shows up in
    server-side logs; correlate by timestamp + node-id if needed.
    """

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def request_id(self) -> str | None:
        """Unique request ID for tracing (``X-SpaceRouter-Request-Id``).

        Populated for HTTP target URLs (gateway injects on the inner
        response). Returns ``None`` for HTTPS targets — see the class
        docstring for the architectural reason. Use server-side logs
        plus timestamp / node-id to correlate HTTPS requests.
        """
        return self._response.headers.get("x-spacerouter-request-id")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __repr__(self) -> str:
        return f"<ProxyResponse [{self._response.status_code}]>"
