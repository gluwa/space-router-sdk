"""SpaceRouter Escrow Client — interact with the TokenPaymentEscrow contract.

Provides EscrowClient for Consumers and Providers to deposit, withdraw,
check balances, and query receipts on the TokenPaymentEscrow contract.
"""

from __future__ import annotations

import logging
from typing import Optional

from eth_account import Account
from eth_utils import to_checksum_address
from web3 import Web3

from spacerouter.payment.eip712 import Receipt, address_to_bytes32

logger = logging.getLogger(__name__)

# Minimal ABI for SDK escrow operations (matches TokenPaymentEscrow.sol)
ESCROW_ABI = [
    {"inputs": [{"type": "uint256", "name": "amount"}], "name": "deposit", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"type": "address", "name": "beneficiary"}, {"type": "uint256", "name": "amount"}], "name": "depositFor", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"type": "address", "name": "client"}], "name": "getBalance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"type": "uint256", "name": "amount"}], "name": "initiateWithdrawal", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "executeWithdrawal", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "cancelWithdrawal", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"type": "address", "name": "client"}], "name": "getWithdrawalRequest", "outputs": [{"type": "uint256", "name": "amount"}, {"type": "uint256", "name": "unlockAt"}, {"type": "bool", "name": "exists"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"type": "address", "name": "client"}, {"type": "string", "name": "requestUUID"}], "name": "isNonceUsed", "outputs": [{"type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "WITHDRAWAL_DELAY", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {"inputs": [{"type": "address", "name": "spender"}, {"type": "uint256", "name": "amount"}], "name": "approve", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"type": "address", "name": "owner"}, {"type": "address", "name": "spender"}], "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"type": "address", "name": "account"}], "name": "balanceOf", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]


class EscrowClient:
    """Client for the TokenPaymentEscrow contract on Creditcoin.

    Parameters
    ----------
    rpc_url : str
        Creditcoin RPC endpoint.
    contract_address : str
        Deployed TokenPaymentEscrow proxy address.
    private_key : str, optional
        Wallet private key for write operations.
    """

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        private_key: Optional[str] = None,
    ) -> None:
        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._contract = self._w3.eth.contract(
            address=to_checksum_address(contract_address),
            abi=ESCROW_ABI,
        )
        self._contract_address = contract_address
        self._account = Account.from_key(private_key) if private_key else None
        self._token_contract = None

        try:
            token_addr = self._contract.functions.token().call()
            self._token_contract = self._w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        except Exception:
            pass

    @property
    def address(self) -> str:
        return self._account.address if self._account else ""

    # ── Read ──────────────────────────────────────────────────────────

    def balance(self, address: str) -> int:
        """Query escrow balance for an address (wei)."""
        return self._contract.functions.getBalance(to_checksum_address(address)).call()

    def token_balance(self, address: str) -> int:
        """Query undeposited SPACE token balance."""
        if not self._token_contract:
            raise RuntimeError("Token contract not available")
        return self._token_contract.functions.balanceOf(to_checksum_address(address)).call()

    def withdrawal_request(self, address: str) -> tuple[int, int, bool]:
        """Query pending withdrawal. Returns ``(amount, unlockAt, exists)``.

        Use this to inspect a request that is in the locked-but-pending
        state. Note: ``balance(address)`` does **not** include this
        amount — the balance is only debited when ``execute_withdrawal``
        runs after the timelock. See the class docstring for the full
        three-phase lifecycle.
        """
        result = self._contract.functions.getWithdrawalRequest(to_checksum_address(address)).call()
        return (result[0], result[1], result[2])

    def is_nonce_used(self, client_address: str, request_uuid: str) -> bool:
        """Check if a receipt UUID has been claimed for a client."""
        return self._contract.functions.isNonceUsed(
            to_checksum_address(client_address), request_uuid
        ).call()

    def withdrawal_delay(self) -> int:
        """Get the withdrawal delay in seconds (5 days = 432000)."""
        return self._contract.functions.WITHDRAWAL_DELAY().call()

    # ── Write ─────────────────────────────────────────────────────────

    def _require_signer(self) -> None:
        if not self._account:
            raise RuntimeError("Private key required for write operations")

    def _send_tx(self, tx_func, gas: int = 500_000) -> str:
        """Build, estimate, sign, and broadcast a tx.

        ``gas`` is a fallback ceiling used only if eth_estimateGas fails (some
        RPCs are flaky on contract calls). The estimator runs against the
        unsigned tx WITHOUT a pre-set gas — pre-setting it confused some
        Creditcoin RPCs into refusing to estimate above the supplied value
        (root cause of v1.5.0-rc.1's "deposit reverts at 200k gas" bug).
        """
        self._require_signer()
        wallet = self._account.address
        tx = tx_func.build_transaction({
            "from": wallet,
            "nonce": self._w3.eth.get_transaction_count(wallet),
            "chainId": self._w3.eth.chain_id,
        })
        try:
            est = self._w3.eth.estimate_gas(tx)
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = gas
        signed = self._w3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt["status"] != 1:
            raise RuntimeError(f"Transaction reverted: {tx_hash.hex()}")
        return tx_hash.hex()

    def deposit(self, amount: int) -> str:
        """Deposit SPACE tokens into escrow. Returns tx hash."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self._require_signer()
        if self._token_contract:
            allowance = self._token_contract.functions.allowance(
                self._account.address, to_checksum_address(self._contract_address)
            ).call()
            if allowance < amount:
                self._send_tx(
                    self._token_contract.functions.approve(
                        to_checksum_address(self._contract_address), amount
                    ), gas=100_000,
                )
        # Deposit observed at ~303k gas on Creditcoin testnet. Set the
        # fallback ceiling above that so we never underestimate when
        # eth_estimateGas is unavailable.
        return self._send_tx(self._contract.functions.deposit(amount), gas=500_000)

    def initiate_withdrawal(self, amount: int) -> str:
        """Phase 1 of 3 — record a withdrawal request with a 5-day timelock.

        This call does **not** move tokens. It only stores
        ``(amount, unlockAt)`` on-chain so the funds are reserved for
        the eventual ``execute_withdrawal`` and the timelock can run.
        Therefore ``balance(address)`` is unchanged after
        ``initiate_withdrawal`` returns. Query
        ``withdrawal_request(address)`` to see the locked-but-pending
        amount.

        Lifecycle:
            1. ``initiate_withdrawal(amount)`` — record request, no
               balance change.
            2. ``execute_withdrawal()`` — after the timelock elapses,
               actually transfers tokens out and debits ``balance``.
            3. ``cancel_withdrawal()`` — at any point before step 2,
               clear the request. Also no balance change because no
               debit ever happened.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return self._send_tx(self._contract.functions.initiateWithdrawal(amount), gas=150_000)

    def execute_withdrawal(self) -> str:
        """Phase 2 of 3 — finalise the pending withdrawal after timelock.

        This is the **only** phase that actually moves tokens. The
        contract transfers the previously-requested amount to the
        client and debits ``balance(address)`` by the same amount.
        Reverts if no request exists or the unlock time has not yet
        passed. See ``initiate_withdrawal`` for the full lifecycle.
        """
        return self._send_tx(self._contract.functions.executeWithdrawal(), gas=150_000)

    def cancel_withdrawal(self) -> str:
        """Phase 3 (alternate) of 3 — clear the pending withdrawal request.

        Removes the on-chain request record. Because
        ``initiate_withdrawal`` never debited the balance, this call
        also produces **no balance change** — that is by design, not a
        bug. ``balance(address)`` was already correct throughout. See
        ``initiate_withdrawal`` for the three-phase lifecycle.
        """
        return self._send_tx(self._contract.functions.cancelWithdrawal(), gas=100_000)
