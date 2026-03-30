"""Tests for v0.2.3 Python SDK client payment modules.

Covers:
- ClientPaymentWallet (challenge signing, receipt signing, recovery)
- ClientReceiptValidator (all 5 checks + timestamp)
- SpaceRouterSPACE (challenge request, header building, frame encoding)
"""
import json
import struct
import time
import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data

from spacerouter.payment.client_wallet import (
    ClientPaymentWallet,
    RECEIPT_EIP712_TYPES,
    RECEIPT_EIP712_DOMAIN_NAME,
    RECEIPT_EIP712_DOMAIN_VERSION,
)
from spacerouter.payment.client_receipt import ClientReceiptValidator, ValidationResult
from spacerouter.payment.spacecoin_client import SpaceRouterSPACE


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def test_key():
    """Generate a test private key."""
    account = Account.create()
    return account.key.hex()


@pytest.fixture
def wallet(test_key):
    """Create a ClientPaymentWallet."""
    return ClientPaymentWallet(
        private_key=test_key,
        chain_id=102031,
        escrow_contract="0x" + "cc" * 20,
    )


@pytest.fixture
def validator(wallet):
    """Create a ClientReceiptValidator."""
    return ClientReceiptValidator(
        client_address=wallet.address,
        max_rate_per_gb_wei=1_000_000_000_000_000_000,  # 1 SPACE/GB
    )


# ── ClientPaymentWallet Tests ────────────────────────────────────


class TestClientPaymentWallet:
    def test_address(self, wallet):
        assert wallet.address.startswith("0x")
        assert len(wallet.address) == 42
        assert wallet.address == wallet.address.lower()

    def test_checksum_address(self, wallet):
        assert wallet.checksum_address.startswith("0x")
        assert len(wallet.checksum_address) == 42

    def test_sign_challenge(self, wallet):
        challenge = "test_challenge_123"
        signature = wallet.sign_challenge(challenge)
        assert len(signature) > 0

        # Verify the signature
        recovered = ClientPaymentWallet.recover_challenge_signer(
            challenge, signature,
        )
        assert recovered == wallet.address

    def test_sign_challenge_different_challenges(self, wallet):
        sig1 = wallet.sign_challenge("challenge_1")
        sig2 = wallet.sign_challenge("challenge_2")
        assert sig1 != sig2

    def test_sign_receipt(self, wallet):
        receipt = {
            "clientPaymentAddress": wallet.checksum_address,
            "nodeCollectionAddress": "0x" + "Ab" * 20,
            "requestId": "0x" + "12" * 16,
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        signature = wallet.sign_receipt(receipt)
        assert len(signature) > 0

    def test_sign_receipt_no_escrow(self, test_key):
        wallet = ClientPaymentWallet(private_key=test_key)
        receipt = {
            "clientPaymentAddress": wallet.checksum_address,
            "nodeCollectionAddress": "0x" + "Ab" * 20,
            "requestId": "0x" + "12" * 16,
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        with pytest.raises(ValueError, match="Escrow contract"):
            wallet.sign_receipt(receipt)

    def test_recover_challenge_signer(self, wallet):
        challenge = "recovery_test"
        signature = wallet.sign_challenge(challenge)
        recovered = ClientPaymentWallet.recover_challenge_signer(challenge, signature)
        assert recovered == wallet.address

    def test_recover_challenge_signer_0x_prefix(self, wallet):
        challenge = "prefix_test"
        signature = wallet.sign_challenge(challenge)
        recovered = ClientPaymentWallet.recover_challenge_signer(
            challenge, "0x" + signature,
        )
        assert recovered == wallet.address

    def test_different_wallets_different_signatures(self, test_key):
        wallet1 = ClientPaymentWallet(private_key=test_key)
        wallet2 = ClientPaymentWallet(private_key=Account.create().key.hex())
        challenge = "same_challenge"

        sig1 = wallet1.sign_challenge(challenge)
        sig2 = wallet2.sign_challenge(challenge)
        assert sig1 != sig2


# ── ClientReceiptValidator Tests ──────────────────────────────────


class TestClientReceiptValidator:
    def test_valid_receipt(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_wrong_client_address(self, validator):
        receipt = {
            "clientPaymentAddress": "0x" + "ff" * 20,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("Client address mismatch" in e for e in result.errors)

    def test_zero_node_address(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "00" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("zero" in e.lower() for e in result.errors)

    def test_empty_request_id(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": "",
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("Request ID" in e for e in result.errors)

    def test_negative_data_bytes(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": -1,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("negative" in e.lower() for e in result.errors)

    def test_excessive_price(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,  # 1 KB
            "priceWei": 10 ** 18,  # 1 SPACE for 1 KB — way too much
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("exceeds maximum" in e for e in result.errors)

    def test_old_timestamp(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()) - 600,  # 10 minutes ago
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("Timestamp drift" in e for e in result.errors)

    def test_future_timestamp(self, validator, wallet):
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()) + 600,  # 10 minutes in future
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert any("Timestamp drift" in e for e in result.errors)

    def test_validation_result_bool(self):
        assert bool(ValidationResult(valid=True, errors=[])) is True
        assert bool(ValidationResult(valid=False, errors=["err"])) is False

    def test_no_rate_limit_check(self, wallet):
        validator = ClientReceiptValidator(
            client_address=wallet.address,
            max_rate_per_gb_wei=0,
        )
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 10 ** 18,
            "timestamp": int(time.time()),
        }
        result = validator.validate(receipt)
        assert result.valid is True  # No rate check = accept any price

    def test_multiple_errors(self, validator):
        receipt = {
            "clientPaymentAddress": "0x" + "ff" * 20,
            "nodeCollectionAddress": "",
            "requestId": "",
            "dataBytes": -1,
            "priceWei": -1,
            "timestamp": 0,
        }
        result = validator.validate(receipt)
        assert result.valid is False
        assert len(result.errors) >= 4


# ── SpaceRouterSPACE Frame Tests ─────────────────────────────────


class TestSpaceRouterSPACEFrames:
    def test_read_receipt_frame(self):
        receipt = {
            "clientPaymentAddress": "0x" + "11" * 20,
            "nodeCollectionAddress": "0x" + "22" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        payload = json.dumps(receipt, separators=(",", ":")).encode()
        frame = struct.pack("!I", len(payload)) + payload

        parsed = SpaceRouterSPACE.read_receipt_frame(frame)
        assert parsed is not None
        assert parsed["dataBytes"] == 1024

    def test_read_receipt_frame_too_short(self):
        assert SpaceRouterSPACE.read_receipt_frame(b"\x00\x00") is None

    def test_read_receipt_frame_incomplete(self):
        payload = b'{"test": 1}'
        frame = struct.pack("!I", len(payload) + 10) + payload  # Length too long
        assert SpaceRouterSPACE.read_receipt_frame(frame) is None

    def test_encode_signature_frame(self):
        frame = SpaceRouterSPACE.encode_signature_frame("0xabc123")
        length = struct.unpack("!I", frame[:4])[0]
        payload = json.loads(frame[4:].decode())
        assert payload["signature"] == "0xabc123"
        assert len(frame) == 4 + length

    def test_roundtrip_frame(self):
        """Encode and decode a signature frame."""
        sig = "0x" + "ab" * 65
        frame = SpaceRouterSPACE.encode_signature_frame(sig)
        length = struct.unpack("!I", frame[:4])[0]
        payload = json.loads(frame[4:4+length].decode())
        assert payload["signature"] == sig


class TestSpaceRouterSPACEHeaders:
    def test_build_auth_headers(self, wallet):
        client = SpaceRouterSPACE(
            gateway_url="http://localhost:8081",
            proxy_url="http://localhost:8080",
            private_key=Account.from_key(wallet._account.key).key.hex(),
            chain_id=102031,
            escrow_contract="0x" + "cc" * 20,
        )
        headers = client.build_auth_headers("test_challenge")
        assert "X-SpaceRouter-Payment-Address" in headers
        assert "X-SpaceRouter-Identity-Address" in headers
        assert "X-SpaceRouter-Challenge-Signature" in headers
        assert "X-SpaceRouter-Challenge" in headers
        assert headers["X-SpaceRouter-Payment-Address"] == wallet.address
        assert headers["X-SpaceRouter-Challenge"] == "test_challenge"

    def test_validate_receipt(self, wallet):
        client = SpaceRouterSPACE(
            gateway_url="http://localhost:8081",
            proxy_url="http://localhost:8080",
            private_key=Account.from_key(wallet._account.key).key.hex(),
            chain_id=102031,
            escrow_contract="0x" + "cc" * 20,
        )
        receipt = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        valid, errors = client.validate_receipt(receipt)
        assert valid is True
        assert len(errors) == 0

    def test_sign_receipt(self, wallet):
        client = SpaceRouterSPACE(
            gateway_url="http://localhost:8081",
            proxy_url="http://localhost:8080",
            private_key=Account.from_key(wallet._account.key).key.hex(),
            chain_id=102031,
            escrow_contract="0x" + "cc" * 20,
        )
        receipt = {
            "clientPaymentAddress": wallet.checksum_address,
            "nodeCollectionAddress": "0x" + "Ab" * 20,
            "requestId": "0x" + "12" * 16,
            "dataBytes": 1024,
            "priceWei": 100,
            "timestamp": int(time.time()),
        }
        signature = client.sign_receipt(receipt)
        assert len(signature) > 0


# ── Integration Tests ─────────────────────────────────────────────


class TestEndToEndFlow:
    def test_challenge_to_receipt_flow(self):
        """Full flow: challenge → sign → validate → receipt → sign → store."""
        account = Account.create()
        chain_id = 102031
        escrow = "0x" + "cc" * 20

        # 1. Create wallet
        wallet = ClientPaymentWallet(
            private_key=account.key.hex(),
            chain_id=chain_id,
            escrow_contract=escrow,
        )

        # 2. Sign challenge
        challenge = "test_challenge_" + uuid.uuid4().hex[:8]
        sig = wallet.sign_challenge(challenge)

        # 3. Verify challenge
        recovered = ClientPaymentWallet.recover_challenge_signer(challenge, sig)
        assert recovered == wallet.address

        # 4. Create receipt
        receipt_data = {
            "clientPaymentAddress": wallet.address,
            "nodeCollectionAddress": "0x" + "ab" * 20,
            "requestId": str(uuid.uuid4()),
            "dataBytes": 1024 * 1024,  # 1 MB
            "priceWei": 953674,  # ~1 SPACE/GB rate for 1MB
            "timestamp": int(time.time()),
        }

        # 5. Validate receipt
        validator = ClientReceiptValidator(
            client_address=wallet.address,
            max_rate_per_gb_wei=1_000_000_000_000_000_000,
        )
        result = validator.validate(receipt_data)
        assert result.valid is True

        # 6. Sign receipt
        rid = receipt_data["requestId"].replace("-", "")[:32]
        eip712_receipt = {
            "clientPaymentAddress": wallet.checksum_address,
            "nodeCollectionAddress": "0x" + "Ab" * 20,
            "requestId": "0x" + rid,
            "dataBytes": receipt_data["dataBytes"],
            "priceWei": receipt_data["priceWei"],
            "timestamp": receipt_data["timestamp"],
        }
        receipt_sig = wallet.sign_receipt(eip712_receipt)
        assert len(receipt_sig) > 0
