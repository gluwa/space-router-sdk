"""SpaceRouter Escrow Client — interact with the SpaceRouterEscrow contract.

Provides EscrowClient for Python SDK users and CLI integration.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Minimal ABI for escrow operations
ESCROW_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "payer", "type": "address"}],
        "name": "escrowBalance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}],
        "name": "initiateWithdrawal",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "completeWithdrawal",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "cancelWithdrawal",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "payer", "type": "address"}],
        "name": "pendingWithdrawal",
        "outputs": [
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "unlockTime", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {
                        "components": [
                            {"internalType": "address", "name": "clientPaymentAddress", "type": "address"},
                            {"internalType": "address", "name": "nodeCollectionAddress", "type": "address"},
                            {"internalType": "bytes16", "name": "requestId", "type": "bytes16"},
                            {"internalType": "uint256", "name": "dataBytes", "type": "uint256"},
                            {"internalType": "uint256", "name": "priceWei", "type": "uint256"},
                            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
                        ],
                        "internalType": "struct ISpaceRouterEscrow.Receipt",
                        "name": "receipt",
                        "type": "tuple",
                    },
                    {"internalType": "bytes", "name": "signature", "type": "bytes"},
                ],
                "internalType": "struct ISpaceRouterEscrow.SignedReceipt[]",
                "name": "receipts",
                "type": "tuple[]",
            }
        ],
        "name": "settleBatch",
        "outputs": [
            {"internalType": "uint256", "name": "paid", "type": "uint256"},
            {"internalType": "uint256", "name": "skipped", "type": "uint256"},
            {"internalType": "uint256", "name": "underfunded", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "spaceToken",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes16", "name": "", "type": "bytes16"}],
        "name": "claimedRequests",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Minimal ERC-20 ABI
ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "spender", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# EIP-712 types for receipt signing (v0.2.2)
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


class EscrowClient:
    """Client for the SpaceRouterEscrow contract.

    Parameters
    ----------
    rpc_url : str
        Creditcoin RPC endpoint.
    contract_address : str
        Deployed SpaceRouterEscrow address.
    private_key : str, optional
        Wallet private key for write operations (deposit, withdraw, settle).
    contract_abi : list, optional
        Custom ABI override.
    """

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        private_key: Optional[str] = None,
        contract_abi: Optional[list] = None,
    ):
        from web3 import Web3
        from eth_account import Account

        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=contract_abi or ESCROW_ABI,
        )
        self._account = Account.from_key(private_key) if private_key else None
        self._contract_address = contract_address
        self._token_contract = None

        # Try to get token contract
        try:
            token_addr = self._contract.functions.spaceToken().call()
            self._token_contract = self._w3.eth.contract(
                address=token_addr,
                abi=ERC20_ABI,
            )
        except Exception:
            pass

    @property
    def address(self) -> str:
        """Wallet address (empty if no private key)."""
        return self._account.address if self._account else ""

    @property
    def contract_address(self) -> str:
        return self._contract_address

    # ── Read Operations ───────────────────────────────────────────────

    def balance(self, address: str) -> int:
        """Query escrow balance for an address (in wei)."""
        return self._contract.functions.escrowBalance(
            self._w3.to_checksum_address(address)
        ).call()

    def pending_withdrawal(self, address: str) -> tuple[int, int]:
        """Query pending withdrawal. Returns (amount, unlockTime)."""
        result = self._contract.functions.pendingWithdrawal(
            self._w3.to_checksum_address(address)
        ).call()
        return (result[0], result[1])

    def is_claimed(self, request_id_hex: str) -> bool:
        """Check if a request ID has been claimed."""
        rid_bytes = bytes.fromhex(request_id_hex.replace("-", "").replace("0x", ""))[:16]
        return self._contract.functions.claimedRequests(rid_bytes).call()

    def token_balance(self, address: str) -> int:
        """Query SPACE token balance (not escrowed)."""
        if not self._token_contract:
            raise RuntimeError("Token contract not available")
        return self._token_contract.functions.balanceOf(
            self._w3.to_checksum_address(address)
        ).call()

    # ── Write Operations ──────────────────────────────────────────────

    def _require_signer(self) -> None:
        if not self._account:
            raise RuntimeError("Private key required for write operations")

    def _send_tx(self, tx_func, gas: int = 200_000) -> str:
        """Build, sign, send a transaction. Returns tx hash hex."""
        self._require_signer()
        wallet = self._account.address
        tx = tx_func.build_transaction({
            "from": wallet,
            "nonce": self._w3.eth.get_transaction_count(wallet),
            "chainId": self._w3.eth.chain_id,
            "gas": gas,
        })
        try:
            est = self._w3.eth.estimate_gas(tx)
            tx["gas"] = int(est * 1.2)
        except Exception:
            pass  # Use default gas

        signed = self._w3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt["status"] != 1:
            raise RuntimeError(f"Transaction reverted: {tx_hash.hex()}")
        return tx_hash.hex()

    def deposit(self, amount: int) -> str:
        """Deposit SPACE tokens into escrow. Returns tx hash."""
        self._require_signer()
        if amount <= 0:
            raise ValueError("Amount must be positive")

        # Approve if needed
        if self._token_contract:
            checksum = self._w3.to_checksum_address(self._contract_address)
            allowance = self._token_contract.functions.allowance(
                self._account.address, checksum
            ).call()
            if allowance < amount:
                self._send_tx(
                    self._token_contract.functions.approve(checksum, amount),
                    gas=100_000,
                )

        return self._send_tx(self._contract.functions.deposit(amount))

    def initiate_withdrawal(self, amount: int) -> str:
        """Initiate escrow withdrawal. Returns tx hash."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return self._send_tx(self._contract.functions.initiateWithdrawal(amount), gas=150_000)

    def complete_withdrawal(self) -> str:
        """Complete pending withdrawal after timelock. Returns tx hash."""
        return self._send_tx(self._contract.functions.completeWithdrawal(), gas=150_000)

    def cancel_withdrawal(self) -> str:
        """Cancel pending withdrawal. Returns tx hash."""
        return self._send_tx(self._contract.functions.cancelWithdrawal(), gas=100_000)

    def settle_batch(self, receipts_file: str) -> str:
        """Submit a batch of signed receipts for settlement.

        Parameters
        ----------
        receipts_file : str
            Path to JSON file containing array of {receipt, signature} objects.

        Returns tx hash.
        """
        self._require_signer()

        with open(receipts_file) as f:
            receipts_data = json.load(f)

        if not isinstance(receipts_data, list) or len(receipts_data) == 0:
            raise ValueError("Receipts file must contain a non-empty array")

        # Convert to contract format
        signed_receipts = []
        for item in receipts_data:
            r = item["receipt"]
            # Convert request_id to bytes16
            rid_hex = r["requestId"].replace("-", "").replace("0x", "")
            rid_bytes = bytes.fromhex(rid_hex)[:16]

            receipt_tuple = (
                self._w3.to_checksum_address(r["clientPaymentAddress"]),
                self._w3.to_checksum_address(r["nodeCollectionAddress"]),
                rid_bytes,
                int(r["dataBytes"]),
                int(r["priceWei"]),
                int(r["timestamp"]),
            )
            sig_bytes = bytes.fromhex(item["signature"].removeprefix("0x"))
            signed_receipts.append((receipt_tuple, sig_bytes))

        # Estimate gas for the batch
        gas = max(200_000, len(signed_receipts) * 100_000)
        return self._send_tx(
            self._contract.functions.settleBatch(signed_receipts),
            gas=gas,
        )

    # ── EIP-712 Signing ───────────────────────────────────────────────

    def sign_receipt(
        self,
        receipt: dict,
        chain_id: int,
        contract_address: str,
    ) -> str:
        """Sign a receipt using EIP-712 (v0.2.2 domain).

        Returns signature as hex string.
        """
        self._require_signer()
        from eth_account.messages import encode_typed_data

        structured_data = {
            "types": RECEIPT_EIP712_TYPES,
            "primaryType": "Receipt",
            "domain": {
                "name": RECEIPT_EIP712_DOMAIN_NAME,
                "version": RECEIPT_EIP712_DOMAIN_VERSION,
                "chainId": chain_id,
                "verifyingContract": contract_address,
            },
            "message": receipt,
        }

        signed = self._account.sign_message(
            encode_typed_data(full_message=structured_data)
        )
        return signed.signature.hex()
