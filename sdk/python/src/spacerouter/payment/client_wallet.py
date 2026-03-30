"""Client payment wallet for v0.2.3 SPACE payments.

Handles EIP-191 challenge signing and EIP-712 receipt signing for
client-to-gateway payment flows.
"""
from __future__ import annotations

import logging
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3

logger = logging.getLogger(__name__)

# EIP-712 types for receipt signing (same as v0.2.2 escrow)
RECEIPT_EIP712_DOMAIN_NAME = "SpaceRouterEscrow"
RECEIPT_EIP712_DOMAIN_VERSION = "1"

RECEIPT_EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Receipt": [
        {"name": "clientPaymentAddress", "type": "address"},
        {"name": "nodeCollectionAddress", "type": "address"},
        {"name": "requestId", "type": "bytes16"},
        {"name": "dataBytes", "type": "uint256"},
        {"name": "priceWei", "type": "uint256"},
        {"name": "timestamp", "type": "uint256"},
    ],
}


class ClientPaymentWallet:
    """Wallet for client SPACE payment operations.

    Provides EIP-191 signing for authentication challenges and
    EIP-712 signing for payment receipts.

    Parameters
    ----------
    private_key : str
        Hex-encoded private key (with or without 0x prefix).
    chain_id : int
        Chain ID for EIP-712 domain (default: Creditcoin 102031).
    escrow_contract : str
        Escrow contract address for EIP-712 domain.
    """

    def __init__(
        self,
        private_key: str,
        chain_id: int = 102031,
        escrow_contract: str = "",
    ):
        self._account = Account.from_key(private_key)
        self._chain_id = chain_id
        self._escrow_contract = escrow_contract

    @property
    def address(self) -> str:
        """Client's payment/identity address (lowercase)."""
        return self._account.address.lower()

    @property
    def checksum_address(self) -> str:
        """Client's payment/identity address (checksummed)."""
        return self._account.address

    def sign_challenge(self, challenge: str) -> str:
        """Sign an authentication challenge (EIP-191).

        Message format: ``space-router:challenge:{challenge}``

        Returns signature as hex string (without 0x prefix).
        """
        message_text = f"space-router:challenge:{challenge}"
        message = encode_defunct(text=message_text)
        signed = self._account.sign_message(message)
        return signed.signature.hex()

    def sign_receipt(self, receipt: dict) -> str:
        """Sign a payment receipt (EIP-712).

        Parameters
        ----------
        receipt : dict
            Receipt with keys: clientPaymentAddress, nodeCollectionAddress,
            requestId (hex bytes16), dataBytes, priceWei, timestamp.

        Returns signature as hex string (without 0x prefix).
        """
        if not self._escrow_contract:
            raise ValueError("Escrow contract address required for receipt signing")

        # Ensure proper types for EIP-712
        message = {
            "clientPaymentAddress": Web3.to_checksum_address(receipt["clientPaymentAddress"]),
            "nodeCollectionAddress": Web3.to_checksum_address(receipt["nodeCollectionAddress"]),
            "requestId": receipt["requestId"],
            "dataBytes": int(receipt["dataBytes"]),
            "priceWei": int(receipt["priceWei"]),
            "timestamp": int(receipt["timestamp"]),
        }

        structured_data = {
            "types": RECEIPT_EIP712_TYPES,
            "primaryType": "Receipt",
            "domain": {
                "name": RECEIPT_EIP712_DOMAIN_NAME,
                "version": RECEIPT_EIP712_DOMAIN_VERSION,
                "chainId": self._chain_id,
                "verifyingContract": self._escrow_contract,
            },
            "message": message,
        }

        signed = self._account.sign_message(
            encode_typed_data(full_message=structured_data)
        )
        return signed.signature.hex()

    @staticmethod
    def recover_challenge_signer(challenge: str, signature_hex: str) -> str:
        """Recover the signer address from a signed challenge.

        Returns lowercase address.
        """
        message_text = f"space-router:challenge:{challenge}"
        message = encode_defunct(text=message_text)
        sig_bytes = bytes.fromhex(signature_hex.removeprefix("0x"))
        recovered = Account.recover_message(message, signature=sig_bytes)
        return recovered.lower()

    @staticmethod
    def recover_receipt_signer(
        receipt: dict,
        signature_hex: str,
        chain_id: int,
        escrow_contract: str,
    ) -> str:
        """Recover the signer address from a signed receipt.

        Returns lowercase address.
        """
        structured_data = {
            "types": RECEIPT_EIP712_TYPES,
            "primaryType": "Receipt",
            "domain": {
                "name": RECEIPT_EIP712_DOMAIN_NAME,
                "version": RECEIPT_EIP712_DOMAIN_VERSION,
                "chainId": chain_id,
                "verifyingContract": escrow_contract,
            },
            "message": receipt,
        }

        sig_bytes = bytes.fromhex(signature_hex.removeprefix("0x"))
        encoded = encode_typed_data(full_message=structured_data)
        recovered = Account.recover_message(encoded, signature=sig_bytes)
        return recovered.lower()
