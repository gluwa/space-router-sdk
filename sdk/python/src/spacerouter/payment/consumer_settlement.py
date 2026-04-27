"""Consumer-side Leg 1 settlement client.

Replaces the broken in-band TCP receipt exchange. After a SPACE-paid
proxy request the Gateway stashes an unsigned Leg 1 receipt in
``pending_client_receipts``. This client pulls the pending receipts
via ``GET /leg1/pending``, signs each with EIP-712, and submits back
via ``POST /leg1/sign`` — the same out-of-band pattern Leg 2 uses
between the Provider and the Coord API.

The client is stateless: every call authenticates with a fresh EIP-191
signature over ``space-router:leg1-<verb>:<addr>:<ts>``. Safe to call
repeatedly; the Gateway side is idempotent.

Usage:
    settler = ConsumerSettlementClient(
        gateway_url="https://gateway:8081",
        private_key="0x...",
    )
    result = await settler.sync_receipts()
    # {"accepted": [uuid, ...], "rejected": [{"request_uuid", "reason"}]}
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import tenacity
from eth_account import Account
from eth_account.messages import encode_defunct

from spacerouter.payment.eip712 import EIP712Domain, Receipt, sign_receipt

logger = logging.getLogger(__name__)


class _RetryableHTTPError(Exception):
    """Wraps a 5xx response so tenacity can retry on it.

    Tenacity's ``retry_if_exception_type`` operates on raised exceptions,
    not on returned values. We raise this internally between attempts and
    convert back to ``httpx.HTTPStatusError`` after the final failure so
    callers see the standard exception type with the verbatim body.
    """

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        body = response.text
        super().__init__(
            f"HTTP {response.status_code} from "
            f"{response.request.method} {response.request.url}: {body}"
        )


# Per spec §9: bounded retry, default 3 attempts, 200ms / 1s / 5s.
# We use exponential backoff seeded so the first wait is 200ms, then 1s, 5s.
_RETRY_KW = dict(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=0.2, min=0.2, max=5.0),
    retry=tenacity.retry_if_exception_type(
        (httpx.TransportError, _RetryableHTTPError),
    ),
    reraise=True,
)


class ConsumerSettlementClient:
    """Fetches pending Leg 1 receipts, signs, submits."""

    def __init__(
        self,
        gateway_url: str,
        private_key: str,
        timeout: float = 10.0,
        verify: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        gateway_url : str
            Gateway management URL (e.g. ``https://gateway:8081``).
        private_key : str
            Consumer's wallet private key. Signs both EIP-191 auth and
            EIP-712 receipts.
        timeout : float
            HTTP timeout per call.
        verify : bool
            TLS verification (set False only for local dev).
        """
        self._gateway_url = gateway_url.rstrip("/")
        self._account = Account.from_key(private_key)
        self._private_key = private_key
        self._timeout = timeout
        self._verify = verify

    @property
    def address(self) -> str:
        return self._account.address

    def _auth_sig(self, verb: str, ts: int) -> str:
        """EIP-191 sig over ``space-router:leg1-<verb>:<addr>:<ts>``."""
        msg = f"space-router:leg1-{verb}:{self._account.address.lower()}:{ts}"
        signed = self._account.sign_message(encode_defunct(text=msg))
        return "0x" + signed.signature.hex()

    async def fetch_pending(self, limit: int = 50) -> dict[str, Any]:
        """Pull unsigned Leg 1 receipts owed by this consumer.

        Returns a dict with ``receipts`` (list) and ``domain`` (EIP-712
        domain to sign under).

        Retries on transport errors and HTTP 5xx with exponential backoff
        (3 attempts, 200ms / 1s / 5s) per spec §9. The verbatim response
        body is surfaced in the raised error message on final failure.
        """
        @tenacity.retry(**_RETRY_KW)
        async def _do() -> dict[str, Any]:
            ts = int(time.time())
            params = {
                "address": self._account.address,
                "ts": ts,
                "sig": self._auth_sig("list-pending", ts),
                "limit": limit,
            }
            async with httpx.AsyncClient(
                timeout=self._timeout, verify=self._verify,
            ) as client:
                r = await client.get(
                    f"{self._gateway_url}/leg1/pending", params=params,
                )
            if 500 <= r.status_code < 600:
                raise _RetryableHTTPError(r)
            r.raise_for_status()
            return r.json()

        try:
            return await _do()
        except _RetryableHTTPError as exc:
            # Surface body verbatim via the standard httpx exception.
            exc.response.raise_for_status()
            raise  # unreachable

    async def submit_signatures(
        self, signatures: list[dict[str, str]],
    ) -> dict[str, Any]:
        """POST ``{request_uuid, signature}`` pairs back to the gateway.

        Returns ``{accepted: [uuid, ...], rejected: [{request_uuid, reason}]}``.

        Retries on transport errors and HTTP 5xx with exponential backoff
        (3 attempts, 200ms / 1s / 5s) per spec §9. The verbatim response
        body is surfaced in the raised error message on final failure.
        """
        if not signatures:
            return {"accepted": [], "rejected": []}

        @tenacity.retry(**_RETRY_KW)
        async def _do() -> dict[str, Any]:
            ts = int(time.time())
            body = {
                "address": self._account.address,
                "ts": ts,
                "sig": self._auth_sig("sign", ts),
                "signatures": signatures,
            }
            async with httpx.AsyncClient(
                timeout=self._timeout, verify=self._verify,
            ) as client:
                r = await client.post(
                    f"{self._gateway_url}/leg1/sign", json=body,
                )
            if 500 <= r.status_code < 600:
                raise _RetryableHTTPError(r)
            r.raise_for_status()
            return r.json()

        try:
            return await _do()
        except _RetryableHTTPError as exc:
            exc.response.raise_for_status()
            raise  # unreachable

    async def sync_receipts(self, limit: int = 50) -> dict[str, Any]:
        """One-shot: fetch pending, sign each, submit, return the outcome.

        Safe to call anytime — after each proxy request for real-time
        settlement, or periodically for batch settlement of accumulated
        receipts.
        """
        pending = await self.fetch_pending(limit=limit)
        receipts = pending.get("receipts", [])
        if not receipts:
            return {"accepted": [], "rejected": [], "pending_count": 0}

        domain_dict = pending["domain"]
        domain = EIP712Domain(
            name=domain_dict["name"],
            version=domain_dict["version"],
            chain_id=int(domain_dict["chainId"]),
            verifying_contract=domain_dict["verifyingContract"],
        )

        signatures: list[dict[str, str]] = []
        for row in receipts:
            receipt = Receipt(
                client_address=row["client_address"],
                node_address=row["node_address"],
                request_uuid=row["request_uuid"],
                data_amount=int(row["data_amount"]),
                total_price=int(row["total_price"]),
            )
            try:
                sig = sign_receipt(self._private_key, receipt, domain)
            except Exception as exc:
                logger.exception(
                    "Failed to sign Leg 1 receipt uuid=%s: %s",
                    receipt.request_uuid, exc,
                )
                continue
            signatures.append({
                "request_uuid": receipt.request_uuid,
                "signature": sig,
            })

        result = await self.submit_signatures(signatures)
        result["pending_count"] = len(receipts)
        logger.info(
            "Leg 1 sync: %d pending → %d accepted, %d rejected",
            len(receipts),
            len(result.get("accepted", [])),
            len(result.get("rejected", [])),
        )
        return result
