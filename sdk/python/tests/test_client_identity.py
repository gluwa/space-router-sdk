"""Tests for ClientIdentity wallet."""

import json
import os
import time

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from spacerouter.identity import ClientIdentity

_w3 = Web3()
_TEST_KEY = "0x" + "ab" * 32
_TEST_ACCOUNT = Account.from_key(_TEST_KEY)
_PASSPHRASE = "test-password-123"


class TestClientIdentityFactoryMethods:
    def test_from_private_key(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        assert identity.address == _TEST_ACCOUNT.address.lower()

    def test_generate(self):
        identity = ClientIdentity.generate()
        assert identity.address.startswith("0x")
        assert len(identity.address) == 42

    def test_generate_with_keystore(self, tmp_path):
        path = str(tmp_path / "identity.key")
        identity = ClientIdentity.generate(keystore_path=path)
        assert os.path.isfile(path)
        assert identity.address.startswith("0x")

    def test_generate_with_encrypted_keystore(self, tmp_path):
        path = str(tmp_path / "identity.json")
        identity = ClientIdentity.generate(keystore_path=path, passphrase=_PASSPHRASE)
        assert os.path.isfile(path)
        content = open(path).read()
        data = json.loads(content)
        assert "crypto" in data or "Crypto" in data

    def test_from_keystore_plaintext(self, tmp_path):
        path = str(tmp_path / "identity.key")
        with open(path, "w") as f:
            f.write(_TEST_KEY + "\n")
        identity = ClientIdentity.from_keystore(path)
        assert identity.address == _TEST_ACCOUNT.address.lower()

    def test_from_keystore_encrypted(self, tmp_path):
        path = str(tmp_path / "identity.json")
        keystore = Account.encrypt(_TEST_KEY, _PASSPHRASE)
        with open(path, "w") as f:
            json.dump(keystore, f)
        identity = ClientIdentity.from_keystore(path, _PASSPHRASE)
        assert identity.address == _TEST_ACCOUNT.address.lower()

    def test_from_keystore_encrypted_no_passphrase(self, tmp_path):
        path = str(tmp_path / "identity.json")
        keystore = Account.encrypt(_TEST_KEY, _PASSPHRASE)
        with open(path, "w") as f:
            json.dump(keystore, f)
        with pytest.raises(ValueError, match="passphrase"):
            ClientIdentity.from_keystore(path)

    def test_direct_init_raises(self):
        with pytest.raises(TypeError, match="generate"):
            ClientIdentity()


class TestClientIdentitySigning:
    def test_sign_message(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        sig = identity.sign_message("hello world")
        msg = encode_defunct(text="hello world")
        recovered = _w3.eth.account.recover_message(msg, signature=sig)
        assert recovered.lower() == identity.address

    def test_sign_auth_header(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        headers = identity.sign_auth_header()
        assert "X-Identity-Address" in headers
        assert "X-Identity-Signature" in headers
        assert "X-Timestamp" in headers
        assert headers["X-Identity-Address"] == identity.address

    def test_sign_auth_header_with_timestamp(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        ts = 1234567890
        headers = identity.sign_auth_header(timestamp=ts)
        assert headers["X-Timestamp"] == "1234567890"

        # Verify signature
        sig = headers["X-Identity-Signature"]
        msg = encode_defunct(text=f"space-router:auth:{identity.address}:{ts}")
        recovered = _w3.eth.account.recover_message(msg, signature=sig)
        assert recovered.lower() == identity.address

    def test_sign_auth_header_timestamp_recent(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        headers = identity.sign_auth_header()
        ts = int(headers["X-Timestamp"])
        assert abs(ts - int(time.time())) < 5


class TestClientIdentityPaymentAddress:
    def test_default_none(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        assert identity.payment_address is None

    def test_set_payment_address(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        identity.payment_address = "0x1234567890ABCDEF1234567890ABCDEF12345678"
        assert identity.payment_address == "0x1234567890abcdef1234567890abcdef12345678"


class TestClientIdentityKeystore:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "identity.json")
        original = ClientIdentity.from_private_key(_TEST_KEY)
        original.save_keystore(path, _PASSPHRASE)

        loaded = ClientIdentity.from_keystore(path, _PASSPHRASE)
        assert loaded.address == original.address

    def test_save_plaintext(self, tmp_path):
        path = str(tmp_path / "identity.key")
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        identity.save_keystore(path)
        assert os.path.isfile(path)
        mode = os.stat(path).st_mode & 0o777
        assert mode == 0o600

    def test_save_encrypted(self, tmp_path):
        path = str(tmp_path / "identity.json")
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        identity.save_keystore(path, _PASSPHRASE)
        content = open(path).read()
        data = json.loads(content)
        assert "crypto" in data or "Crypto" in data


class TestClientIdentityNoKeyLeakage:
    def test_no_raw_key_in_public_attrs(self):
        identity = ClientIdentity.from_private_key(_TEST_KEY)
        key_hex = _TEST_KEY[2:]  # without 0x prefix
        public_attrs = [a for a in dir(identity) if not a.startswith("_")]
        for attr in public_attrs:
            val = getattr(identity, attr)
            if isinstance(val, str):
                assert key_hex not in val, f"Raw key leaked via {attr}"
