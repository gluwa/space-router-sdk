"""Consumer wallet for SPACE payment authentication and receipt signing.

Handles:
- EIP-191 challenge signing (for authentication)
- EIP-712 receipt signing (for payment acknowledgment)
"""

from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct

from spacerouter.payment.eip712 import EIP712Domain, Receipt, sign_receipt, recover_receipt_signer


class ClientPaymentWallet:
    """Consumer-side wallet for SPACE payment flows.

    Parameters
    ----------
    private_key : str
        Consumer's wallet private key (hex, with or without 0x prefix).
    """

    def __init__(self, private_key: str) -> None:
        if not private_key:
            raise ValueError("Private key is required")
        self._account = Account.from_key(private_key)
        self.address = self._account.address

    def sign_challenge(self, challenge: str) -> str:
        """Sign a challenge with EIP-191 for authentication.

        Message format: ``space-router:challenge:{challenge}``
        Returns 0x-prefixed hex signature.
        """
        message = f"space-router:challenge:{challenge}"
        signable = encode_defunct(text=message)
        signed = self._account.sign_message(signable)
        return "0x" + signed.signature.hex()

    def sign_receipt(self, receipt: Receipt, domain: EIP712Domain) -> str:
        """Sign a receipt with EIP-712 for payment acknowledgment.

        Returns 0x-prefixed hex signature.
        """
        return sign_receipt(self._account.key.hex(), receipt, domain)

    def build_auth_headers(self, challenge: str) -> dict[str, str]:
        """Build the proxy request headers for SPACE payment auth.

        Returns a dict of headers to include in the proxy request.
        """
        signature = self.sign_challenge(challenge)
        return {
            "X-SpaceRouter-Payment-Address": self.address,
            "X-SpaceRouter-Identity-Address": self.address,
            "X-SpaceRouter-Challenge": challenge,
            "X-SpaceRouter-Challenge-Signature": signature,
        }

    @staticmethod
    def verify_receipt_signature(
        receipt: Receipt,
        signature: str,
        domain: EIP712Domain,
        expected_signer: str,
    ) -> bool:
        """Verify that a receipt was signed by the expected address."""
        try:
            recovered = recover_receipt_signer(receipt, signature, domain)
            return recovered.lower() == expected_signer.lower()
        except Exception:
            return False
