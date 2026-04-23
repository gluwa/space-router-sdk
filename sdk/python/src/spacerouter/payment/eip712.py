"""EIP-712 typed data signing for TokenPaymentEscrow receipts.

Domain and Receipt types match the on-chain contract exactly:
  - Contract: TokenPaymentEscrow.sol (UUPS proxy)
  - TYPEHASH: Receipt(address clientAddress,bytes32 nodeAddress,string requestUUID,uint256 dataAmount,uint256 totalPrice)
  - Domain: configurable name/version set at contract initialize()

Reference: escrow-payment/test/shared/signature.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_bytes, to_checksum_address

logger = logging.getLogger(__name__)

# EIP-712 types matching TokenPaymentEscrow.sol Receipt struct
RECEIPT_EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Receipt": [
        {"name": "clientAddress", "type": "address"},
        {"name": "nodeAddress", "type": "bytes32"},
        {"name": "requestUUID", "type": "string"},
        {"name": "dataAmount", "type": "uint256"},
        {"name": "totalPrice", "type": "uint256"},
    ],
}


@dataclass(frozen=True)
class EIP712Domain:
    """EIP-712 domain separator parameters."""

    name: str
    version: str
    chain_id: int
    verifying_contract: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "chainId": self.chain_id,
            "verifyingContract": to_checksum_address(self.verifying_contract),
        }


@dataclass
class Receipt:
    """On-chain Receipt struct for TokenPaymentEscrow.

    Fields match the Solidity struct exactly:
      address clientAddress   — signer / payer (whose escrow balance is debited)
      bytes32 nodeAddress     — provider identity (EVM address zero-padded to 32 bytes)
      string  requestUUID     — unique per-payer nonce (UUID v4)
      uint256 dataAmount      — bytes served
      uint256 totalPrice      — tokens owed (in token's smallest unit)

    In Leg 1: clientAddress = consumer (payer), nodeAddress = gateway
    In Leg 2: clientAddress = gateway (payer), nodeAddress = provider
    """

    client_address: str
    node_address: str  # bytes32 hex string (0x-prefixed, 66 chars)
    request_uuid: str
    data_amount: int
    total_price: int

    def to_eip712_message(self) -> dict:
        """Convert to the dict expected by EIP-712 signTypedData."""
        return {
            "clientAddress": to_checksum_address(self.client_address),
            "nodeAddress": self.node_address,
            "requestUUID": self.request_uuid,
            "dataAmount": self.data_amount,
            "totalPrice": self.total_price,
        }

    def to_contract_tuple(self) -> tuple:
        """Convert to the tuple format expected by claimBatch()."""
        node_bytes = to_bytes(hexstr=self.node_address)
        return (
            to_checksum_address(self.client_address),
            node_bytes,
            self.request_uuid,
            self.data_amount,
            self.total_price,
        )

    def to_json_dict(self) -> dict:
        """Serializable dict for wire protocol / storage."""
        return {
            "clientAddress": self.client_address,
            "nodeAddress": self.node_address,
            "requestUUID": self.request_uuid,
            "dataAmount": self.data_amount,
            "totalPrice": self.total_price,
        }

    @classmethod
    def from_json_dict(cls, d: dict) -> Receipt:
        return cls(
            client_address=d["clientAddress"],
            node_address=d["nodeAddress"],
            request_uuid=d["requestUUID"],
            data_amount=int(d["dataAmount"]),
            total_price=int(d["totalPrice"]),
        )


def address_to_bytes32(address: str) -> str:
    """Zero-pad an EVM address to a bytes32 hex string.

    Matches: ethers.zeroPadValue(address, 32)
    Example: 0xAbC...123 → 0x000000000000000000000000AbC...123
    """
    addr_bytes = to_bytes(hexstr=address)
    padded = b"\x00" * (32 - len(addr_bytes)) + addr_bytes
    return "0x" + padded.hex()


def sign_receipt(
    private_key: str,
    receipt: Receipt,
    domain: EIP712Domain,
) -> str:
    """Sign a Receipt using EIP-712 typed data.

    Returns the signature as a hex string (0x-prefixed).
    """
    structured_data = {
        "types": RECEIPT_EIP712_TYPES,
        "primaryType": "Receipt",
        "domain": domain.to_dict(),
        "message": receipt.to_eip712_message(),
    }
    account = Account.from_key(private_key)
    signed = account.sign_message(encode_typed_data(full_message=structured_data))
    return "0x" + signed.signature.hex()


def recover_receipt_signer(
    receipt: Receipt,
    signature: str,
    domain: EIP712Domain,
) -> str:
    """Recover the signer address from an EIP-712 signed receipt.

    Returns the recovered address (checksummed).
    """
    structured_data = {
        "types": RECEIPT_EIP712_TYPES,
        "primaryType": "Receipt",
        "domain": domain.to_dict(),
        "message": receipt.to_eip712_message(),
    }
    signable = encode_typed_data(full_message=structured_data)
    return Account.recover_message(signable, signature=bytes.fromhex(signature.removeprefix("0x")))
