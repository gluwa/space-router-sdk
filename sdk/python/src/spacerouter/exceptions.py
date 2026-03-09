"""SpaceRouter SDK exceptions.

Maps to the error codes returned by the proxy gateway:
- 407 proxy_auth_required  -> AuthenticationError
- 429 rate_limited         -> RateLimitError
- 502 upstream_error       -> UpstreamError
- 503 no_nodes_available   -> NoNodesAvailableError
"""


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


class NoNodesAvailableError(SpaceRouterError):
    """503 Service Unavailable — no residential nodes currently available."""


class UpstreamError(SpaceRouterError):
    """502 Bad Gateway — target unreachable via residential node."""

    def __init__(
        self,
        message: str,
        *,
        node_id: str | None = None,
        status_code: int | None = 502,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, request_id=request_id)
        self.node_id = node_id
