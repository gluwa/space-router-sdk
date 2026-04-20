"""Tests for SpaceRouter Python SDK payment modules (Phase 5).

Covers:
- ClientPaymentWallet (challenge signing, receipt signing, auth headers)
- EIP-712 Receipt types (signing, recovery, serialization)
- SpaceRouterSPACE client (receipt validation, header building)
- EscrowClient (balance queries, deposit validation)
"""

import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from spacerouter.payment.eip712 import (
    EIP712Domain,
    Receipt,
    address_to_bytes32,
    recover_receipt_signer,
    sign_receipt,
)
from spacerouter.payment.client_wallet import ClientPaymentWallet
from spacerouter.payment.spacecoin_client import SpaceRouterSPACE
from spacerouter.escrow import EscrowClient

# ── Constants ─────────────────────────────────────────────────────────

CLIENT_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
CLIENT_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
GATEWAY_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
GATEWAY_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

TEST_DOMAIN = EIP712Domain(
    name="TokenPaymentEscrow",
    version="1",
    chain_id=102031,
    verifying_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
)


# ── ClientPaymentWallet ───────────────────────────────────────────────


class TestClientPaymentWallet:
    def test_creates_with_address(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        assert w.address.lower() == CLIENT_ADDRESS.lower()

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="required"):
            ClientPaymentWallet("")

    def test_sign_challenge(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        challenge = "a" * 64
        sig = w.sign_challenge(challenge)
        assert sig.startswith("0x")

        # Verify with EIP-191 recovery
        message = f"space-router:challenge:{challenge}"
        signable = encode_defunct(text=message)
        recovered = Account.recover_message(
            signable, signature=bytes.fromhex(sig[2:])
        )
        assert recovered.lower() == CLIENT_ADDRESS.lower()

    def test_sign_receipt(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1000,
            total_price=50,
        )
        sig = w.sign_receipt(receipt, TEST_DOMAIN)
        assert sig.startswith("0x")

        recovered = recover_receipt_signer(receipt, sig, TEST_DOMAIN)
        assert recovered.lower() == CLIENT_ADDRESS.lower()

    def test_build_auth_headers(self):
        w = ClientPaymentWallet(CLIENT_KEY)
        headers = w.build_auth_headers("abc123")
        assert headers["X-SpaceRouter-Payment-Address"] == w.address
        assert headers["X-SpaceRouter-Identity-Address"] == w.address
        assert headers["X-SpaceRouter-Challenge"] == "abc123"
        assert headers["X-SpaceRouter-Challenge-Signature"].startswith("0x")

    def test_verify_receipt_signature_valid(self):
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid="test-uuid",
            data_amount=100,
            total_price=10,
        )
        sig = sign_receipt(CLIENT_KEY, receipt, TEST_DOMAIN)
        assert ClientPaymentWallet.verify_receipt_signature(
            receipt, sig, TEST_DOMAIN, CLIENT_ADDRESS,
        ) is True

    def test_verify_receipt_signature_wrong_signer(self):
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid="test-uuid",
            data_amount=100,
            total_price=10,
        )
        sig = sign_receipt(GATEWAY_KEY, receipt, TEST_DOMAIN)  # Wrong key
        assert ClientPaymentWallet.verify_receipt_signature(
            receipt, sig, TEST_DOMAIN, CLIENT_ADDRESS,
        ) is False


# ── SpaceRouterSPACE ──────────────────────────────────────────────────


class TestSpaceRouterSPACE:
    def _make_client(self, **overrides) -> SpaceRouterSPACE:
        defaults = {
            "gateway_url": "http://localhost:8081",
            "proxy_url": "http://localhost:8080",
            "private_key": CLIENT_KEY,
            "chain_id": 102031,
            "escrow_contract": "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
        }
        defaults.update(overrides)
        return SpaceRouterSPACE(**defaults)

    def test_creates_with_address(self):
        c = self._make_client()
        assert c.address.lower() == CLIENT_ADDRESS.lower()

    def test_build_auth_headers(self):
        c = self._make_client()
        headers = c.build_auth_headers("challenge123")
        assert "X-SpaceRouter-Payment-Address" in headers
        assert "X-SpaceRouter-Challenge-Signature" in headers

    def test_sign_receipt(self):
        c = self._make_client()
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=5000,
            total_price=100,
        )
        sig = c.sign_receipt(receipt)
        assert sig.startswith("0x")

        recovered = recover_receipt_signer(receipt, sig, c.domain)
        assert recovered.lower() == CLIENT_ADDRESS.lower()

    def test_validate_receipt_valid(self):
        c = self._make_client()
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1024 ** 3,
            total_price=10 ** 18,
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is True
        assert errors == []

    def test_validate_receipt_wrong_address(self):
        c = self._make_client()
        receipt = Receipt(
            client_address=GATEWAY_ADDRESS,  # Wrong
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1000,
            total_price=10,
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is False
        assert any("mismatch" in e for e in errors)

    def test_validate_receipt_excessive_rate(self):
        c = self._make_client(max_rate_per_gb=10 ** 18)  # 1 SPACE/GB max
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1024,  # 1 KB
            total_price=10 ** 18,  # 1 SPACE for 1 KB = way too expensive
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is False
        assert any("rate" in e.lower() for e in errors)

    def test_validate_receipt_no_rate_limit(self):
        c = self._make_client(max_rate_per_gb=None)
        receipt = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=1024,
            total_price=10 ** 18,  # Expensive but no limit set
        )
        valid, errors = c.validate_receipt(receipt)
        assert valid is True


# ── EscrowClient ──────────────────────────────────────────────────────


class TestEscrowClientSDK:
    def test_escrow_client_instantiation(self):
        """EscrowClient can be instantiated (lazy RPC connect)."""
        client = EscrowClient(
            "http://fake:8545",
            "0x0000000000000000000000000000000000000001",
        )
        assert client.address == ""  # No private key

    def test_deposit_requires_positive(self):
        """EscrowClient.deposit should reject zero/negative amounts."""
        client = EscrowClient(
            "http://fake:8545",
            "0x0000000000000000000000000000000000000001",
            private_key=CLIENT_KEY,
        )
        with pytest.raises(ValueError, match="positive"):
            client.deposit(0)

    def test_address_to_bytes32(self):
        b32 = address_to_bytes32(CLIENT_ADDRESS)
        assert len(b32) == 66
        assert b32.startswith("0x")

    def test_receipt_json_roundtrip(self):
        r = Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid="test-uuid-sdk",
            data_amount=9999,
            total_price=42,
        )
        d = r.to_json_dict()
        restored = Receipt.from_json_dict(d)
        assert restored.client_address == r.client_address
        assert restored.request_uuid == r.request_uuid
        assert restored.data_amount == r.data_amount
        assert restored.total_price == r.total_price


# ── Byte count validation (new in feat/sdk-byte-validation) ───────────

class TestByteCountValidation:
    """SpaceRouterSPACE.validate_receipt rejects inflated dataAmount vs local count."""

    def _client(self, **kwargs):
        defaults = dict(
            gateway_url="http://gw:8081",
            proxy_url="http://gw:8080",
            private_key=CLIENT_KEY,
            chain_id=TEST_DOMAIN.chain_id,
            escrow_contract=TEST_DOMAIN.verifying_contract,
        )
        defaults.update(kwargs)
        return SpaceRouterSPACE(**defaults)

    def _receipt(self, data_amount: int = 10_000, total_price: int = 0):
        return Receipt(
            client_address=CLIENT_ADDRESS,
            node_address=address_to_bytes32(GATEWAY_ADDRESS),
            request_uuid=str(uuid.uuid4()),
            data_amount=data_amount,
            total_price=total_price,
        )

    def test_matching_bytes_pass(self):
        c = self._client()
        r = self._receipt(data_amount=10_000)
        ok, errors = c.validate_receipt(r, observed_bytes=10_000)
        assert ok, errors

    def test_within_tolerance_pass(self):
        """Gateway claims 5% more — default byte_tolerance is 5%."""
        c = self._client(byte_tolerance=0.05)
        r = self._receipt(data_amount=10_500)
        ok, _ = c.validate_receipt(r, observed_bytes=10_000)
        assert ok

    def test_over_tolerance_rejects(self):
        c = self._client(byte_tolerance=0.05)
        r = self._receipt(data_amount=50_000)  # 5x inflation
        ok, errors = c.validate_receipt(r, observed_bytes=10_000)
        assert not ok
        assert any("dataAmount" in e for e in errors)

    def test_absolute_floor_protects_small_requests(self):
        """Tiny observed byte count: absolute floor (1 KB default) must apply."""
        c = self._client(byte_tolerance=0.05, byte_tolerance_abs_min=1024)
        # observed=100, 5% = 5 bytes; floor says allow up to +1024 bytes slack
        r = self._receipt(data_amount=500)
        ok, _ = c.validate_receipt(r, observed_bytes=100)
        assert ok, "floor should tolerate overhead on tiny requests"

        # Over the floor → reject
        r2 = self._receipt(data_amount=2000)
        ok2, _ = c.validate_receipt(r2, observed_bytes=100)
        assert not ok2

    def test_no_observed_bytes_skips_check(self):
        """When caller doesn't supply observed_bytes, byte check is skipped."""
        c = self._client()
        r = self._receipt(data_amount=999_999_999)
        ok, _ = c.validate_receipt(r)  # no observed_bytes
        assert ok

    def test_sign_after_validation_raises_on_fraud(self):
        c = self._client(byte_tolerance=0.05)
        r = self._receipt(data_amount=50_000)
        with pytest.raises(ValueError, match="dataAmount"):
            c.sign_receipt_after_validation(r, observed_bytes=10_000)

    def test_sign_after_validation_signs_on_success(self):
        c = self._client()
        r = self._receipt(data_amount=10_000)
        sig = c.sign_receipt_after_validation(r, observed_bytes=10_000)
        assert sig.startswith("0x")
        assert len(sig) == 132  # 0x + 130 hex chars (65 bytes)


