"""SpaceRouter SDK exceptions.

Maps to the error codes returned by the proxy gateway:
- 407 proxy_auth_required  -> AuthenticationError
- 429 rate_limited         -> RateLimitError
- 502 upstream_error       -> UpstreamError
- 503 no_nodes_available   -> NoNodesAvailableError

Plus v1.5 escrow settlement:
- /leg1/sign rejections    -> SettlementRejected (opt-in via strict=True)
"""

from __future__ import annotations


class SpaceRouterError(Exception):
    """Base exception for all SpaceRouter SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class AuthenticationError(SpaceRouterError):
    """407 Proxy Authentication Required — invalid or missing API key."""


class RateLimitError(SpaceRouterError):
    """429 Too Many Requests — per-key rate limit exceeded."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: int,
        status_code: int | None = 429,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, request_id=request_id)
        self.retry_after = retry_after


class QuotaExceededError(SpaceRouterError):
    """402 Payment Required — monthly data transfer limit exceeded."""

    def __init__(
        self,
        message: str,
        *,
        limit_bytes: int = 0,
        used_bytes: int = 0,
        status_code: int | None = 402,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, request_id=request_id)
        self.limit_bytes = limit_bytes
        self.used_bytes = used_bytes


class NoNodesAvailableError(SpaceRouterError):
    """503 Service Unavailable — no residential nodes currently available."""


class UpstreamError(SpaceRouterError):
    """502 Bad Gateway — target unreachable via residential node."""


class SettlementRejected(SpaceRouterError):
    """Raised when the gateway rejects one or more Leg 1 signatures.

    Surfaces the full ``rejected`` list returned by ``POST /leg1/sign``.
    Each entry is a dict ``{"request_uuid": str, "reason": str}``. Raised
    only when the caller opts in via ``strict=True`` on
    :meth:`ConsumerSettlementClient.submit_signatures` /
    :class:`SpaceRouterSPACE` ``strict_settlement=True`` /
    ``SpaceRouter(..., auto_settle=True)`` with a strict payment client.
    """

    def __init__(
        self,
        reasons: list[dict],
        *,
        message: str | None = None,
    ) -> None:
        if message is None:
            count = len(reasons)
            message = f"Gateway rejected {count} Leg 1 signature(s)"
        super().__init__(message)
        self.reasons = reasons
