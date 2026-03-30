"""SpaceRouterSPACE — high-level client for SPACE-paid proxy usage.

Handles the full v0.2.3 flow:
1. Request challenge from gateway
2. Sign challenge with identity key
3. Build auth headers
4. Make proxied request
5. Exchange and sign receipt
"""
from __future__ import annotations

import json
import logging
import struct
from typing import Optional

import httpx

from spacerouter.payment.client_wallet import ClientPaymentWallet
from spacerouter.payment.client_receipt import ClientReceiptValidator

logger = logging.getLogger(__name__)


class SpaceRouterSPACE:
    """Client for SPACE-paid proxy requests through Space Router.

    Parameters
    ----------
    gateway_url : str
        Gateway management API URL (e.g., ``http://gateway.spacerouter.io:8081``).
    proxy_url : str
        Gateway proxy URL (e.g., ``http://gateway.spacerouter.io:8080``).
    private_key : str
        Client wallet private key for signing.
    chain_id : int
        Chain ID for EIP-712 domain.
    escrow_contract : str
        Escrow contract address.
    max_rate_per_gb_wei : int
        Maximum acceptable rate per GB in wei (for receipt validation).
    """

    def __init__(
        self,
        gateway_url: str,
        proxy_url: str,
        private_key: str,
        chain_id: int = 102031,
        escrow_contract: str = "",
        max_rate_per_gb_wei: int = 0,
    ):
        self._gateway_url = gateway_url.rstrip("/")
        self._proxy_url = proxy_url.rstrip("/")
        self._wallet = ClientPaymentWallet(
            private_key=private_key,
            chain_id=chain_id,
            escrow_contract=escrow_contract,
        )
        self._validator = ClientReceiptValidator(
            client_address=self._wallet.address,
            max_rate_per_gb_wei=max_rate_per_gb_wei,
        )
        self._chain_id = chain_id
        self._escrow_contract = escrow_contract
        self._http_client: httpx.AsyncClient | None = None

    @property
    def address(self) -> str:
        """Client payment address."""
        return self._wallet.address

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def request_challenge(self) -> str:
        """Request an authentication challenge from the gateway.

        Returns the challenge string.
        """
        client = await self._get_client()
        response = await client.get(f"{self._gateway_url}/auth/challenge")
        response.raise_for_status()
        data = response.json()
        return data["challenge"]

    def build_auth_headers(self, challenge: str) -> dict[str, str]:
        """Build authentication headers for a SPACE-paid proxy request.

        Parameters
        ----------
        challenge : str
            Challenge obtained from ``request_challenge()``.

        Returns
        -------
        dict
            Headers to include in the proxy request.
        """
        signature = self._wallet.sign_challenge(challenge)
        return {
            "X-SpaceRouter-Payment-Address": self._wallet.address,
            "X-SpaceRouter-Identity-Address": self._wallet.address,
            "X-SpaceRouter-Challenge-Signature": signature,
            "X-SpaceRouter-Challenge": challenge,
        }

    def validate_receipt(self, receipt: dict) -> tuple[bool, list[str]]:
        """Validate a receipt from the gateway.

        Returns (is_valid, errors).
        """
        result = self._validator.validate(receipt)
        return result.valid, result.errors

    def sign_receipt(self, receipt: dict) -> str:
        """Sign a validated receipt.

        Parameters
        ----------
        receipt : dict
            Receipt data from the gateway.

        Returns
        -------
        str
            Hex-encoded EIP-712 signature.
        """
        # Convert requestId to bytes16 hex format for EIP-712
        rid = receipt.get("requestId", "")
        if rid and not rid.startswith("0x"):
            rid = "0x" + rid.replace("-", "")[:32]

        eip712_receipt = {
            "clientPaymentAddress": receipt["clientPaymentAddress"],
            "nodeCollectionAddress": receipt["nodeCollectionAddress"],
            "requestId": rid,
            "dataBytes": int(receipt["dataBytes"]),
            "priceWei": int(receipt["priceWei"]),
            "timestamp": int(receipt["timestamp"]),
        }
        return self._wallet.sign_receipt(eip712_receipt)

    async def get(
        self,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a SPACE-paid GET request through the proxy.

        Handles challenge → auth → request flow automatically.
        """
        return await self._proxied_request("GET", url, **kwargs)

    async def post(
        self,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a SPACE-paid POST request through the proxy."""
        return await self._proxied_request("POST", url, **kwargs)

    async def _proxied_request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a SPACE-paid proxied request.

        1. Get challenge
        2. Build auth headers
        3. Send request through proxy
        """
        challenge = await self.request_challenge()
        auth_headers = self.build_auth_headers(challenge)

        # Merge auth headers with any user-provided headers
        headers = kwargs.pop("headers", {})
        headers.update(auth_headers)

        client = await self._get_client()
        response = await client.request(
            method,
            url,
            headers=headers,
            proxy=self._proxy_url,
            **kwargs,
        )
        return response

    @staticmethod
    def read_receipt_frame(data: bytes) -> Optional[dict]:
        """Parse a length-prefixed receipt frame from raw bytes.

        Returns the parsed receipt dict or None.
        """
        if len(data) < 4:
            return None
        length = struct.unpack("!I", data[:4])[0]
        if len(data) < 4 + length:
            return None
        try:
            return json.loads(data[4:4 + length].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    @staticmethod
    def encode_signature_frame(signature: str) -> bytes:
        """Encode a signature response as a length-prefixed frame."""
        payload = json.dumps({"signature": signature}, separators=(",", ":")).encode("utf-8")
        return struct.pack("!I", len(payload)) + payload
