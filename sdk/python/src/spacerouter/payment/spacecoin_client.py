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


class SpaceRouterSPACE:
    """High-level Consumer client for SPACE-token proxy payments.

    Parameters
    ----------
    gateway_url : str
        Management API URL (e.g., ``http://gateway:8081``) for /auth/challenge.
    proxy_url : str
        Proxy endpoint URL (e.g., ``http://gateway:8080``).
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
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.proxy_url = proxy_url.rstrip("/")
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

    @property
    def address(self) -> str:
        return self.wallet.address

    async def request_challenge(self) -> str:
        """Request a one-time challenge from the gateway.

        Returns the challenge string.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.gateway_url}/auth/challenge",
                timeout=10.0,
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
        settler = ConsumerSettlementClient(
            gateway_url=self.gateway_url,
            private_key=self._private_key,
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
