"""SpaceRouter proxy clients.

Provides :class:`SpaceRouter` (sync) and :class:`AsyncSpaceRouter` (async)
for routing HTTP requests through the Space Router residential proxy network.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import httpx

from spacerouter.exceptions import (
    AuthenticationError,
    NoNodesAvailableError,
    QuotaExceededError,
    RateLimitError,
    SettlementRejected,
    UpstreamError,
)
from spacerouter.models import ProxyResponse

if TYPE_CHECKING:
    from spacerouter.payment.spacecoin_client import SpaceRouterSPACE

logger = logging.getLogger(__name__)

# Headers v1.5 payment injects on every CONNECT. User-supplied request
# headers MUST NOT override these (see spec §4 single-use challenges).
_PAYMENT_HEADER_KEYS = (
    "X-SpaceRouter-Payment-Address",
    "X-SpaceRouter-Identity-Address",
    "X-SpaceRouter-Challenge",
    "X-SpaceRouter-Challenge-Signature",
)


# Single shared executor for sync-world bridges to async payment calls.
# Lazy-init: tests that never touch payment never spin a thread.
_SYNC_BRIDGE_EXECUTOR: ThreadPoolExecutor | None = None


def _run_async(coro):
    """Run an async coroutine to completion from sync code.

    The naive ``asyncio.run(coro)`` errors if a loop is already running on
    the calling thread. We hand off to a worker thread that owns its own
    fresh loop — safe whether or not the caller is inside one.
    """
    global _SYNC_BRIDGE_EXECUTOR
    if _SYNC_BRIDGE_EXECUTOR is None:
        _SYNC_BRIDGE_EXECUTOR = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="spacerouter-payment",
        )

    def _runner():
        return asyncio.run(coro)

    return _SYNC_BRIDGE_EXECUTOR.submit(_runner).result()


def _merge_payment_headers(
    user_headers: Any, payment_headers: dict[str, str],
) -> dict[str, str]:
    """Merge payment headers into user-supplied headers.

    Payment headers take precedence on collision (case-insensitive) — a
    stale Challenge value from the caller must never shadow a fresh one.
    Returns a brand new dict; never mutates inputs.
    """
    out: dict[str, str] = {}
    if user_headers:
        # httpx accepts dict / list[tuple] / Headers; normalise via dict().
        try:
            out = dict(user_headers)
        except (TypeError, ValueError):
            out = {k: v for k, v in user_headers}  # type: ignore[union-attr]
    payment_lower = {k.lower() for k in payment_headers}
    out = {k: v for k, v in out.items() if k.lower() not in payment_lower}
    out.update(payment_headers)
    return out

_DEFAULT_HTTP_GATEWAY = "https://gateway.spacerouter.org"

_REGION_RE = __import__("re").compile(r"^[A-Z]{2}$")


def _validate_region(region: str) -> None:
    """Raise ``ValueError`` if *region* is not a 2-letter country code."""
    if not _REGION_RE.match(region):
        raise ValueError(
            f"region must be a 2-letter country code (ISO 3166-1 alpha-2), got {region!r}"
        )


def _build_proxy(
    api_key: str,
    gateway_url: str,
    protocol: str,
    region: str | None,
    ip_type: str | None = None,
) -> httpx.Proxy | str:
    """Build an httpx-compatible proxy specification with embedded credentials."""
    parsed = urlparse(gateway_url)
    host = parsed.hostname or "localhost"
    scheme = parsed.scheme or ("socks5" if protocol == "socks5" else "https")

    if protocol == "socks5":
        port = parsed.port or 1080
        proxy_url = f"socks5://{api_key}:@{host}:{port}"
        return proxy_url

    port = parsed.port or (443 if scheme == "https" else 8080)
    proxy_url = f"{scheme}://{host}:{port}"

    # Always send an explicit Proxy-Authorization header.  httpx stores
    # URL-embedded credentials in ``raw_auth`` but httpcore may not
    # convert them into a header on the CONNECT request.
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    proxy_headers: dict[str, str] = {
        "Proxy-Authorization": f"Basic {token}",
    }

    # Routing headers must go on the proxy CONNECT request (not the tunnelled
    # request) so the gateway can read them for node selection.  httpx.Proxy
    # accepts a ``headers`` dict that is sent with every proxy negotiation.
    if region:
        _validate_region(region)
        proxy_headers["X-SpaceRouter-Region"] = region
    if ip_type:
        proxy_headers["X-SpaceRouter-IP-Type"] = ip_type

    return httpx.Proxy(proxy_url, headers=proxy_headers)


def _check_proxy_errors(response: httpx.Response) -> None:
    """Raise typed exceptions for proxy-layer errors (402/407/429/502/503)."""
    request_id = response.headers.get("x-spacerouter-request-id")

    if response.status_code == 402:
        try:
            body = response.json()
        except Exception:
            body = {}
        raise QuotaExceededError(
            body.get("message", "Monthly data transfer limit exceeded"),
            limit_bytes=body.get("limit_bytes", 0),
            used_bytes=body.get("used_bytes", 0),
            status_code=402,
            request_id=request_id,
        )

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
        raise UpstreamError(
            "Target unreachable via residential node",
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
        region: str | None = None,
        ip_type: str | None = None,
        timeout: float = 30.0,
        payment: SpaceRouterSPACE | None = None,
        auto_settle: bool = False,
        **httpx_kwargs: Any,
    ) -> None:
        self._api_key = api_key
        self._gateway_url = gateway_url
        self._protocol = protocol
        self._region = region
        self._ip_type = ip_type
        self._timeout = timeout
        self._payment = payment
        self._auto_settle = auto_settle

        self._verify = httpx_kwargs.pop("verify", True)
        self._httpx_kwargs = httpx_kwargs
        proxy = _build_proxy(api_key, gateway_url, protocol, region, ip_type)
        self._client = httpx.Client(
            proxy=proxy, timeout=timeout, verify=self._verify, **httpx_kwargs,
        )

    # -- HTTP methods -------------------------------------------------------

    def request(self, method: str, url: str, **kwargs: Any) -> ProxyResponse:
        """Send a request through the SpaceRouter proxy.

        When the client was constructed with ``payment=...`` the v1.5
        payment auth headers are fetched fresh per call. They MUST land
        on the proxy CONNECT request (not the tunnelled inner request)
        so the gateway can read them — the inner request is TLS-encrypted
        and opaque to the gateway. We achieve this by building a fresh
        ``httpx.Proxy(headers=...)`` per call and constructing a
        throwaway ``httpx.Client`` for that single request.

        When ``auto_settle`` is also ``True``, ``payment.sync_receipts()``
        is run after a successful response. Settlement failures are
        logged at WARN by default; if the payment client was built with
        ``strict_settlement=True``, :class:`SettlementRejected`
        propagates.
        """
        if self._payment is not None:
            challenge = _run_async(self._payment.request_challenge())
            payment_headers = self._payment.build_auth_headers(challenge)
            # Rebuild the proxy with payment headers stamped onto CONNECT.
            # Fresh challenges are single-use, so a per-request client is
            # the simplest correct shape; httpx.Client construction is
            # cheap (no connect happens until .request() is called).
            proxy = _build_proxy(
                self._api_key, self._gateway_url, self._protocol,
                self._region, self._ip_type,
            )
            if isinstance(proxy, httpx.Proxy):
                merged_headers = _merge_payment_headers(
                    proxy.headers, payment_headers,
                )
                proxy = httpx.Proxy(str(proxy.url), headers=merged_headers)
            with httpx.Client(
                proxy=proxy, timeout=self._timeout, verify=self._verify,
                **self._httpx_kwargs,
            ) as paid_client:
                response = paid_client.request(method, url, **kwargs)
        else:
            response = self._client.request(method, url, **kwargs)
        _check_proxy_errors(response)
        proxy_resp = ProxyResponse(response)

        if self._payment is not None and self._auto_settle:
            try:
                _run_async(self._payment.sync_receipts())
            except SettlementRejected:
                # Strict mode: bubble up so caller halts.
                raise
            except Exception:
                logger.warning(
                    "auto_settle: sync_receipts failed; receipts remain "
                    "queued (will retry on next call or manual sync)",
                    exc_info=True,
                )
        return proxy_resp

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
        region: str | None = None,
        ip_type: str | None = None,
    ) -> SpaceRouter:
        """Return a new client with different routing preferences.

        Forwards the parent's ``verify`` and any other ``**httpx_kwargs``
        so customisations like ``verify=False`` (testnet self-signed
        certs) survive the clone — pre-rc.4 they were silently dropped
        and the routing-derived child tripped ``CERTIFICATE_VERIFY_FAILED``.
        """
        return SpaceRouter(
            self._api_key,
            gateway_url=self._gateway_url,
            protocol=self._protocol,
            region=region,
            ip_type=ip_type,
            timeout=self._timeout,
            payment=self._payment,
            auto_settle=self._auto_settle,
            verify=self._verify,
            **self._httpx_kwargs,
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
        region: str | None = None,
        ip_type: str | None = None,
        timeout: float = 30.0,
        payment: SpaceRouterSPACE | None = None,
        auto_settle: bool = False,
        **httpx_kwargs: Any,
    ) -> None:
        self._api_key = api_key
        self._gateway_url = gateway_url
        self._protocol = protocol
        self._region = region
        self._ip_type = ip_type
        self._timeout = timeout
        self._payment = payment
        self._auto_settle = auto_settle

        self._verify = httpx_kwargs.pop("verify", True)
        self._httpx_kwargs = httpx_kwargs
        proxy = _build_proxy(api_key, gateway_url, protocol, region, ip_type)
        self._client = httpx.AsyncClient(
            proxy=proxy, timeout=timeout, verify=self._verify, **httpx_kwargs,
        )

    # -- HTTP methods -------------------------------------------------------

    async def request(self, method: str, url: str, **kwargs: Any) -> ProxyResponse:
        """Send a request through the SpaceRouter proxy.

        When the client was constructed with ``payment=...`` the v1.5
        payment auth headers are fetched fresh per call. They MUST land
        on the proxy CONNECT request (not the tunnelled inner request)
        so the gateway can read them — the inner request is TLS-encrypted
        and opaque to the gateway. Mirror of the sync ``SpaceRouter``
        fix: build a fresh ``httpx.Proxy(headers=...)`` per call and
        construct a throwaway ``httpx.AsyncClient`` for that single
        request.
        """
        if self._payment is not None:
            challenge = await self._payment.request_challenge()
            payment_headers = self._payment.build_auth_headers(challenge)
            proxy = _build_proxy(
                self._api_key, self._gateway_url, self._protocol,
                self._region, self._ip_type,
            )
            if isinstance(proxy, httpx.Proxy):
                merged_headers = _merge_payment_headers(
                    proxy.headers, payment_headers,
                )
                proxy = httpx.Proxy(str(proxy.url), headers=merged_headers)
            async with httpx.AsyncClient(
                proxy=proxy, timeout=self._timeout, verify=self._verify,
                **self._httpx_kwargs,
            ) as paid_client:
                response = await paid_client.request(method, url, **kwargs)
        else:
            response = await self._client.request(method, url, **kwargs)
        _check_proxy_errors(response)
        proxy_resp = ProxyResponse(response)

        if self._payment is not None and self._auto_settle:
            try:
                await self._payment.sync_receipts()
            except SettlementRejected:
                raise
            except Exception:
                logger.warning(
                    "auto_settle: sync_receipts failed; receipts remain "
                    "queued (will retry on next call or manual sync)",
                    exc_info=True,
                )
        return proxy_resp

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
        region: str | None = None,
        ip_type: str | None = None,
    ) -> AsyncSpaceRouter:
        """Return a new client with different routing preferences.

        Forwards the parent's ``verify`` and any other ``**httpx_kwargs``
        so customisations like ``verify=False`` (testnet self-signed
        certs) survive the clone — pre-rc.4 they were silently dropped
        and the routing-derived child tripped ``CERTIFICATE_VERIFY_FAILED``.
        """
        return AsyncSpaceRouter(
            self._api_key,
            gateway_url=self._gateway_url,
            protocol=self._protocol,
            region=region,
            ip_type=ip_type,
            timeout=self._timeout,
            payment=self._payment,
            auto_settle=self._auto_settle,
            verify=self._verify,
            **self._httpx_kwargs,
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
