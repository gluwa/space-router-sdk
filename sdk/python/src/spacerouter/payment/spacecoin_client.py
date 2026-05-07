"""High-level SPACE payment client for SpaceRouter Consumers.

Usage:
    consumer = SpaceRouterSPACE(
        gateway_url="http://gateway:8081",
        proxy_url="http://gateway:8080",
        private_key="0x...",
        chain_id=102031,
        escrow_contract="0x...",
    )

    # 1. Get challenge
    challenge = await consumer.request_challenge()

    # 2. Build auth headers
    headers = consumer.build_auth_headers(challenge)

    # 3. Make proxied request with those headers
    # (via httpx proxy or direct connection)
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from spacerouter.payment.client_wallet import ClientPaymentWallet
from spacerouter.payment.eip712 import EIP712Domain, Receipt

logger = logging.getLogger(__name__)


# HTTP verbs that callers sometimes try on SpaceRouterSPACE by mistake (e.g.
# old QA bundles documenting ``consumer.get(url)``). The class is a wallet +
# receipt signer, not an HTTP client; converting the cryptic AttributeError
# into an actionable hint saves a round-trip with QA.
_HTTP_METHOD_NAMES = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "request",
})


class SpaceRouterSPACE:
    """High-level Consumer client for SPACE-token proxy payments.

    **Two URLs, two purposes.** The ``proxy_url`` parameter is the base
    proxy endpoint (typically ``https://gateway.example.com``, port 443
    or 8080) where the SDK routes HTTP CONNECT requests for your
    application traffic. The ``gateway_url`` is the management API
    endpoint (typically the same hostname on port 8081) where the SDK
    fetches auth challenges and settles Leg 1 receipts. **They are two
    different ports on the same gateway server** — sending management
    requests to the proxy listener returns HTTP 407 because the proxy
    port only handles CONNECT.

    Parameters
    ----------
    gateway_url : str
        Management API URL used for ``/auth/challenge`` and ``/leg1/...``
        calls when ``management_url`` is not set. In a typical deployment
        this is ``https://gateway.example.com:8081`` while ``proxy_url``
        points at port 443/8080 on the same host. If you only have one
        URL handy, point ``gateway_url`` at the management endpoint.
    proxy_url : str
        Proxy endpoint URL (e.g., ``https://gateway.example.com:8080`` or
        ``:443``). This is the CONNECT listener; the SDK passes it to the
        ``SpaceRouter`` proxy client for tunnelled application traffic.
        Do **not** point this at the management port — see "Common
        error: HTTP 407" below.
    private_key : str
        Consumer's wallet private key.
    chain_id : int
        Creditcoin chain ID (102031 for testnet).
    escrow_contract : str
        TokenPaymentEscrow proxy address.
    domain_name : str
        EIP-712 domain name (default: ``TokenPaymentEscrow``).
    domain_version : str
        EIP-712 domain version (default: ``1``).
    max_rate_per_gb : int, optional
        Maximum acceptable rate per GB (reject receipts above this).
    timeout : float
        HTTP timeout (seconds) used for gateway calls (challenge fetch,
        settlement). Default 30.0.
    verify : bool | str
        TLS verification for gateway calls. ``True`` (default) uses the
        system CA bundle; ``False`` disables verification (local dev
        only); a path string selects a custom CA bundle.
    management_url : str, optional
        Explicit URL for the gateway's management API (the host that
        serves ``/auth/challenge`` and ``/leg1/*``). If your gateway
        uses different ports for proxy traffic vs. management API — the
        typical deployment, with proxy on :8080 and management on
        :8081 — pass ``management_url`` so the SDK never confuses the
        two. When ``None`` (default) the SDK falls back to
        ``gateway_url`` for management calls, preserving the rc.5
        single-URL behaviour. Sending ``GET /auth/challenge`` to the
        proxy listener returns ``HTTP 407`` because that listener only
        accepts ``CONNECT`` — passing ``management_url`` is the fix.

    Common error: HTTP 407
    ----------------------
    If ``request_challenge()`` (or any management call) returns
    ``HTTP 407 Proxy Authentication Required``, you have almost
    certainly swapped ``proxy_url`` and ``gateway_url`` (or pointed
    ``gateway_url`` / ``management_url`` at the proxy port). The proxy
    listener only accepts ``CONNECT`` — every other verb is answered
    with 407. Double-check that ``gateway_url`` resolves to the
    management port (typically :8081) and ``proxy_url`` resolves to the
    CONNECT listener (typically :443 or :8080).
    """

    def __init__(
        self,
        gateway_url: str,
        proxy_url: str,
        private_key: str,
        chain_id: int = 102031,
        escrow_contract: str = "",
        domain_name: str = "TokenPaymentEscrow",
        domain_version: str = "1",
        max_rate_per_gb: Optional[int] = None,
        byte_tolerance: float = 0.05,
        byte_tolerance_abs_min: int = 1024,
        strict_settlement: bool = False,
        timeout: float = 30.0,
        verify: bool | str = True,
        management_url: Optional[str] = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.proxy_url = proxy_url.rstrip("/")
        # Management API host for /auth/challenge and /leg1/*. Defaults
        # to ``gateway_url`` so existing single-URL callers keep working;
        # the explicit kwarg lets deployments split proxy (:8080) from
        # management (:8081) — sending GET /auth/challenge to the proxy
        # listener returns 407 because that port only speaks CONNECT.
        self.management_url = (management_url or gateway_url).rstrip("/")
        self.wallet = ClientPaymentWallet(private_key)
        # Retained so sync_receipts() can hand it to ConsumerSettlementClient
        # without reaching into wallet internals. Kept private.
        self._private_key = private_key
        self.domain = EIP712Domain(
            name=domain_name,
            version=domain_version,
            chain_id=chain_id,
            verifying_contract=escrow_contract,
        )
        self.max_rate_per_gb = max_rate_per_gb
        # Tolerance for gateway's claimed dataAmount vs local byte count.
        # Accept whichever is larger: relative (byte_tolerance) or absolute (byte_tolerance_abs_min).
        # The gateway is stricter (~1%) because it trusts its own observation; consumers sit
        # behind TLS framing overhead and keep-alive noise, so a slightly looser tolerance
        # avoids false rejections while still catching gross overcharging.
        self.byte_tolerance = byte_tolerance
        self.byte_tolerance_abs_min = byte_tolerance_abs_min
        # Whether to surface SettlementRejected when /leg1/sign reports
        # rejected receipts. Read by SpaceRouter(auto_settle=True) so the
        # caller's strict choice flows through the auto-pay path. Spec §9.
        self.strict_settlement = strict_settlement
        # HTTP knobs for gateway calls. ``_timeout`` covers both the challenge
        # fetch here and the ConsumerSettlementClient instance handed out by
        # ``sync_receipts``; ``_verify`` plumbs the same TLS bundle through.
        self._timeout = timeout
        self._verify = verify

    @property
    def address(self) -> str:
        return self.wallet.address

    def __getattr__(self, name: str):
        """Catch HTTP-verb-style accesses on the wallet façade.

        ``SpaceRouterSPACE`` is the payment object passed to
        ``SpaceRouter(payment=...)``; it does not itself send HTTP. Old
        QA bundles still document ``consumer.get(url)`` which crashes
        with a cryptic ``AttributeError``. Surface a directive hint so
        the caller knows to wrap with :class:`SpaceRouter` instead.

        ``__getattr__`` only runs after normal attribute resolution has
        failed, so this never shadows real attributes.
        """
        if name in _HTTP_METHOD_NAMES:
            raise AttributeError(
                f"SpaceRouterSPACE has no `.{name}()` method — it's a "
                "wallet + receipt signer, not an HTTP client.\n"
                "For paid HTTP requests, wrap it with SpaceRouter:\n"
                "\n"
                "    from spacerouter import SpaceRouter\n"
                "    with SpaceRouter(consumer.address.lower(), "
                "payment=consumer, auto_settle=True) as cli:\n"
                "        resp = cli." + name + "(url)\n"
                "\n"
                "See https://docs.spacecoin.org/spacerouter/consumers/"
                "pay-with-space.html#step-4"
            )
        raise AttributeError(
            f"{type(self).__name__!s} object has no attribute {name!r}"
        )

    async def request_challenge(self) -> str:
        """Request a one-time challenge from the gateway.

        Hits the management API (``self.management_url``) — that is the
        endpoint that serves ``GET /auth/challenge``. The proxy listener
        on :8080 / :443 only handles ``CONNECT`` and returns 407 for a
        plain GET, so this call must never go there.

        Returns the challenge string.
        """
        async with httpx.AsyncClient(verify=self._verify) as client:
            resp = await client.get(
                f"{self.management_url}/auth/challenge",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["challenge"]

    def build_auth_headers(self, challenge: str) -> dict[str, str]:
        """Build proxy request headers for SPACE payment authentication."""
        return self.wallet.build_auth_headers(challenge)

    def sign_receipt(self, receipt: Receipt) -> str:
        """Sign a receipt received from the gateway after a proxy request."""
        return self.wallet.sign_receipt(receipt, self.domain)

    async def sync_receipts(
        self, limit: int = 50, *, strict: Optional[bool] = None,
    ) -> dict:
        """Settle any pending Leg 1 receipts owed by this consumer.

        Fetches unsigned receipts from the gateway's
        ``GET /leg1/pending``, signs each with EIP-712, and submits via
        ``POST /leg1/sign``. Returns ``{accepted, rejected, pending_count}``.

        Call this after each paid proxy request for immediate settlement,
        or periodically for batch settlement. Safe and idempotent — the
        gateway's consume step is atomic and duplicate calls are no-ops.

        Parameters
        ----------
        strict : bool, optional
            Override ``strict_settlement`` for this call. When effectively
            ``True`` and any receipt is rejected, raises
            :class:`SettlementRejected`.
        """
        from spacerouter.payment.consumer_settlement import (
            ConsumerSettlementClient,
        )
        # Reuse the consumer's private key. ConsumerSettlementClient holds
        # its own httpx client so callers don't need to pool one here.
        # Plumb the same timeout/verify so settlement honours the caller's
        # TLS posture and timeout budget. Also pass ``management_url`` —
        # ``/leg1/*`` is on the same management host as ``/auth/challenge``
        # and pre-rc.6 we silently used ``gateway_url`` here, which broke
        # for deployments that split the proxy and management ports.
        settler = ConsumerSettlementClient(
            gateway_url=self.management_url,
            private_key=self._private_key,
            timeout=self._timeout,
            verify=self._verify,
        )
        effective_strict = (
            self.strict_settlement if strict is None else strict
        )
        return await settler.sync_receipts(limit=limit, strict=effective_strict)

    def validate_receipt(
        self,
        receipt: Receipt,
        observed_bytes: Optional[int] = None,
    ) -> tuple[bool, list[str]]:
        """Validate a receipt from the gateway.

        Parameters
        ----------
        receipt : Receipt
            The receipt returned by the gateway for signing.
        observed_bytes : int, optional
            The consumer's locally-counted request+response byte total. When
            supplied, the receipt's ``dataAmount`` is checked against it with
            tolerance ``max(byte_tolerance * observed, byte_tolerance_abs_min)``.
            Omit to skip byte validation (e.g. when the caller cannot measure).

        Returns (is_valid, list_of_errors).
        """
        errors = []

        # Check client address matches our wallet
        if receipt.client_address.lower() != self.address.lower():
            errors.append(
                f"clientAddress mismatch: expected {self.address}, got {receipt.client_address}"
            )

        # Check price is reasonable
        if receipt.total_price < 0:
            errors.append("totalPrice is negative")

        if self.max_rate_per_gb is not None and receipt.data_amount > 0:
            gb = 1024 ** 3
            effective_rate = (receipt.total_price * gb) // receipt.data_amount
            if effective_rate > self.max_rate_per_gb:
                errors.append(
                    f"Effective rate {effective_rate} exceeds max {self.max_rate_per_gb}"
                )

        # Byte count check vs locally-observed bytes.
        if observed_bytes is not None:
            claimed = receipt.data_amount
            slack = max(int(observed_bytes * self.byte_tolerance), self.byte_tolerance_abs_min)
            if claimed > observed_bytes + slack:
                errors.append(
                    f"dataAmount {claimed} exceeds observed {observed_bytes} by more than "
                    f"tolerance ({slack} bytes = max({self.byte_tolerance:.1%}, "
                    f"{self.byte_tolerance_abs_min}))"
                )
            elif claimed < 0:
                errors.append(f"dataAmount is negative: {claimed}")

        return len(errors) == 0, errors

    def sign_receipt_after_validation(
        self,
        receipt: Receipt,
        observed_bytes: Optional[int] = None,
    ) -> str:
        """Validate the receipt (incl. byte count) and sign it. Raises on failure.

        This is the recommended entry point for consumer code that has a local
        byte count — validating-then-signing in one call makes it harder to
        accidentally sign an unvalidated receipt.
        """
        ok, errors = self.validate_receipt(receipt, observed_bytes=observed_bytes)
        if not ok:
            raise ValueError(
                "Refusing to sign receipt (uuid=" + receipt.request_uuid + "): " + "; ".join(errors)
            )
        return self.sign_receipt(receipt)
