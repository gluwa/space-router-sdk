"""SpaceRouter proxy clients.

Provides :class:`SpaceRouter` (sync) and :class:`AsyncSpaceRouter` (async)
for routing HTTP requests through the Space Router residential proxy network.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from spacerouter.exceptions import (
    AuthenticationError,
    NoNodesAvailableError,
    RateLimitError,
    UpstreamError,
)
from spacerouter.models import ProxyResponse

IpType = Literal["residential", "mobile", "datacenter", "business"]

_DEFAULT_HTTP_GATEWAY = "http://gateway.spacerouter.org:8080"
_DEFAULT_SOCKS5_GATEWAY = "socks5://gateway.spacerouter.org:1080"


def _build_proxy(
    api_key: str,
    gateway_url: str,
    protocol: str,
    ip_type: str | None,
    region: str | None,
) -> httpx.Proxy | str:
    """Build an httpx-compatible proxy specification with embedded credentials."""
    parsed = urlparse(gateway_url)
    host = parsed.hostname or "localhost"

    if protocol == "socks5":
        port = parsed.port or 1080
        proxy_url = f"socks5://{api_key}:@{host}:{port}"
    else:
        port = parsed.port or 8080
        proxy_url = f"http://{api_key}:@{host}:{port}"

    # Routing headers must go on the proxy CONNECT request (not the tunnelled
    # request) so the gateway can read them for node selection.  httpx.Proxy
    # accepts a ``headers`` dict that is sent with every proxy negotiation.
    proxy_headers: dict[str, str] = {}
    if ip_type:
        proxy_headers["X-SpaceRouter-IP-Type"] = ip_type
    if region:
        proxy_headers["X-SpaceRouter-Region"] = region

    if proxy_headers:
        return httpx.Proxy(proxy_url, headers=proxy_headers)
    return proxy_url


def _check_proxy_errors(response: httpx.Response) -> None:
    """Raise typed exceptions for proxy-layer errors (407/429/502/503)."""
    request_id = response.headers.get("x-spacerouter-request-id")

    if response.status_code == 407:
        raise AuthenticationError(
            "Invalid or missing API key",
            status_code=407,
            request_id=request_id,
        )

    if response.status_code == 429:
        retry_after = int(response.headers.get("retry-after", "60"))
        raise RateLimitError(
            "Rate limit exceeded",
            retry_after=retry_after,
            status_code=429,
            request_id=request_id,
        )

    if response.status_code == 502:
        node_id = response.headers.get("x-spacerouter-node")
        raise UpstreamError(
            "Target unreachable via residential node",
            node_id=node_id,
            status_code=502,
            request_id=request_id,
        )

    if response.status_code == 503:
        try:
            body = response.json()
        except Exception:
            body = {}
        if body.get("error") == "no_nodes_available":
            raise NoNodesAvailableError(
                "No residential nodes currently available",
                status_code=503,
                request_id=request_id,
            )


# ---------------------------------------------------------------------------
# Synchronous client
# ---------------------------------------------------------------------------


class SpaceRouter:
    """Synchronous proxy client for the Space Router network.

    Example::

        with SpaceRouter("sr_live_xxx") as client:
            resp = client.get("https://example.com")
            print(resp.status_code, resp.node_id)
    """

    def __init__(
        self,
        api_key: str,
        *,
        gateway_url: str = _DEFAULT_HTTP_GATEWAY,
        protocol: Literal["http", "socks5"] = "http",
        ip_type: IpType | None = None,
        region: str | None = None,
        timeout: float = 30.0,
        **httpx_kwargs: Any,
    ) -> None:
        self._api_key = api_key
        self._gateway_url = gateway_url
        self._protocol = protocol
        self._ip_type = ip_type
        self._region = region
        self._timeout = timeout

        proxy = _build_proxy(api_key, gateway_url, protocol, ip_type, region)
        self._client = httpx.Client(proxy=proxy, timeout=timeout, **httpx_kwargs)

    # -- HTTP methods -------------------------------------------------------

    def request(self, method: str, url: str, **kwargs: Any) -> ProxyResponse:
        """Send a request through the SpaceRouter proxy."""
        response = self._client.request(method, url, **kwargs)
        _check_proxy_errors(response)
        return ProxyResponse(response)

    def get(self, url: str, **kwargs: Any) -> ProxyResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> ProxyResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> ProxyResponse:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> ProxyResponse:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> ProxyResponse:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> ProxyResponse:
        return self.request("HEAD", url, **kwargs)

    # -- Routing ------------------------------------------------------------

    def with_routing(
        self,
        *,
        ip_type: IpType | None = None,
        region: str | None = None,
    ) -> SpaceRouter:
        """Return a new client with different routing preferences."""
        return SpaceRouter(
            self._api_key,
            gateway_url=self._gateway_url,
            protocol=self._protocol,
            ip_type=ip_type,
            region=region,
            timeout=self._timeout,
        )

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SpaceRouter:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"SpaceRouter(protocol={self._protocol!r}, "
            f"gateway={self._gateway_url!r})"
        )


# ---------------------------------------------------------------------------
# Asynchronous client
# ---------------------------------------------------------------------------


class AsyncSpaceRouter:
    """Asynchronous proxy client for the Space Router network.

    Example::

        async with AsyncSpaceRouter("sr_live_xxx") as client:
            resp = await client.get("https://example.com")
            print(resp.status_code, resp.node_id)
    """

    def __init__(
        self,
        api_key: str,
        *,
        gateway_url: str = _DEFAULT_HTTP_GATEWAY,
        protocol: Literal["http", "socks5"] = "http",
        ip_type: IpType | None = None,
        region: str | None = None,
        timeout: float = 30.0,
        **httpx_kwargs: Any,
    ) -> None:
        self._api_key = api_key
        self._gateway_url = gateway_url
        self._protocol = protocol
        self._ip_type = ip_type
        self._region = region
        self._timeout = timeout

        proxy = _build_proxy(api_key, gateway_url, protocol, ip_type, region)
        self._client = httpx.AsyncClient(proxy=proxy, timeout=timeout, **httpx_kwargs)

    # -- HTTP methods -------------------------------------------------------

    async def request(self, method: str, url: str, **kwargs: Any) -> ProxyResponse:
        """Send a request through the SpaceRouter proxy."""
        response = await self._client.request(method, url, **kwargs)
        _check_proxy_errors(response)
        return ProxyResponse(response)

    async def get(self, url: str, **kwargs: Any) -> ProxyResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> ProxyResponse:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> ProxyResponse:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> ProxyResponse:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> ProxyResponse:
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> ProxyResponse:
        return await self.request("HEAD", url, **kwargs)

    # -- Routing ------------------------------------------------------------

    def with_routing(
        self,
        *,
        ip_type: IpType | None = None,
        region: str | None = None,
    ) -> AsyncSpaceRouter:
        """Return a new client with different routing preferences."""
        return AsyncSpaceRouter(
            self._api_key,
            gateway_url=self._gateway_url,
            protocol=self._protocol,
            ip_type=ip_type,
            region=region,
            timeout=self._timeout,
        )

    # -- Lifecycle ----------------------------------------------------------

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSpaceRouter:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return (
            f"AsyncSpaceRouter(protocol={self._protocol!r}, "
            f"gateway={self._gateway_url!r})"
        )
