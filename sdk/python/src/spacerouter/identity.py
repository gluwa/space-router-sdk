"""Node identity keypair management for the SpaceRouter SDK.

Generates and persists a secp256k1 keypair used for signing authenticated
API requests.  Default storage: ``~/.spacerouter/identity.key``.
"""

import json
import os
import time
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

_w3 = Web3()

DEFAULT_IDENTITY_PATH = str(Path.home() / ".spacerouter" / "identity.key")


def load_or_create_identity(key_path: str = DEFAULT_IDENTITY_PATH) -> tuple[str, str]:
    """Load or generate a secp256k1 identity keypair.

    Returns ``(private_key_hex, address)``.
    """
    if os.path.isfile(key_path):
        with open(key_path) as f:
            private_key = f.read().strip()
        account = Account.from_key(private_key)
        return private_key, account.address.lower()

    account = Account.create()
    private_key = account.key.hex()

    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    with open(key_path, "w") as f:
        f.write(private_key + "\n")
    os.chmod(key_path, 0o600)

    return private_key, account.address.lower()


def get_address(private_key: str) -> str:
    """Derive the checksummed-lower Ethereum address from a private key."""
    return Account.from_key(private_key).address.lower()


def sign_request(private_key: str, action: str, target: str) -> tuple[str, int]:
    """Sign a Space Router API request.

    Returns ``(signature_hex, timestamp)``.
    """
    timestamp = int(time.time())
    message_text = f"space-router:{action}:{target}:{timestamp}"
    message = encode_defunct(text=message_text)
    signed = _w3.eth.account.sign_message(message, private_key=private_key)
    return signed.signature.hex(), timestamp


def create_vouching_signature(
    private_key: str, staking_address: str, collection_address: str,
) -> tuple[str, int]:
    """Sign a vouching message: identity wallet vouches for staking + collection wallets.

    Message format: ``space-router:vouch:{staking_address}:{collection_address}:{timestamp}``

    Returns ``(signature_hex, timestamp)``.
    """
    timestamp = int(time.time())
    message_text = f"space-router:vouch:{staking_address.lower()}:{collection_address.lower()}:{timestamp}"
    message = encode_defunct(text=message_text)
    signed = _w3.eth.account.sign_message(message, private_key=private_key)
    return signed.signature.hex(), timestamp


# ---------------------------------------------------------------------------
# Client Identity Wallet (v0.2.0)
# ---------------------------------------------------------------------------

class ClientIdentity:
    """Client-side identity wallet for wallet-authenticated requests.

    The private key is stored internally as an ``eth_account.Account`` object
    and is never exposed as a string attribute. Use :meth:`sign_message` for
    signing.

    Example::

        identity = ClientIdentity.generate()
        headers = identity.sign_auth_header()
    """

    def __init__(self, *, _account: Account | None = None) -> None:
        if _account is None:
            raise TypeError(
                "Use ClientIdentity.generate(), .from_private_key(), or "
                ".from_keystore() to create an instance."
            )
        # Double-underscore triggers Python name mangling: external access
        # requires ``_ClientIdentity__account``, preventing accidental exposure.
        self.__account = _account
        # Cache lowercased address — avoids repeated .lower() allocation on every
        # property access and every sign_auth_header() call.
        self._address: str = _account.address.lower()
        self._payment_address: str | None = None

    @classmethod
    def from_private_key(cls, private_key: str) -> "ClientIdentity":
        """Create from a raw private key.

        The key is consumed and stored internally as an Account object —
        the original string is not retained.
        """
        account = Account.from_key(private_key)
        return cls(_account=account)

    @classmethod
    def generate(
        cls, keystore_path: str | None = None, passphrase: str = "",
    ) -> "ClientIdentity":
        """Generate a new identity wallet.

        If *keystore_path* is provided, the key is persisted to disk
        (encrypted when *passphrase* is non-empty).
        """
        account = Account.create()
        instance = cls(_account=account)
        if keystore_path:
            instance.save_keystore(keystore_path, passphrase)
        return instance

    @classmethod
    def from_keystore(cls, path: str, passphrase: str = "") -> "ClientIdentity":
        """Load from a Web3 encrypted keystore JSON file.

        Also supports plaintext hex key files for migration convenience.
        """
        with open(path) as f:
            content = f.read().strip()

        # Try JSON parse; if it fails, fall through to raw hex.
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = None

        # Keystore detected — decryption errors must NOT fall through to hex.
        if isinstance(data, dict) and ("crypto" in data or "Crypto" in data):
            if not passphrase:
                raise ValueError(
                    f"Keystore at {path!r} is encrypted — passphrase required."
                )
            private_key_bytes = Account.decrypt(data, passphrase)
            account = Account.from_key(private_key_bytes)
            return cls(_account=account)

        # Raw hex key file
        account = Account.from_key(content)
        return cls(_account=account)

    @property
    def address(self) -> str:
        """Identity address (lowercase, 0x-prefixed)."""
        return self._address

    @property
    def payment_address(self) -> str | None:
        """Optional payment wallet address."""
        return self._payment_address

    @payment_address.setter
    def payment_address(self, address: str) -> None:
        """Set/swap payment wallet."""
        self._payment_address = address.lower()

    def sign_message(self, message: str) -> str:
        """EIP-191 sign a message. Returns 0x-prefixed hex signature."""
        msg = encode_defunct(text=message)
        signed = _w3.eth.account.sign_message(msg, private_key=self.__account.key)
        return "0x" + signed.signature.hex()

    def sign_auth_header(self, timestamp: int | None = None) -> dict[str, str]:
        """Generate auth headers for Coordination API requests.

        Returns a dict with ``X-Identity-Address``, ``X-Identity-Signature``,
        and ``X-Timestamp`` headers.

        Server-side timestamp validation window is ±300 seconds.
        """
        ts = timestamp if timestamp is not None else int(time.time())
        message = f"space-router:auth:{self.address}:{ts}"
        signature = self.sign_message(message)
        return {
            "X-Identity-Address": self.address,
            "X-Identity-Signature": signature,
            "X-Timestamp": str(ts),
        }

    def save_keystore(self, path: str, passphrase: str = "") -> None:
        """Export to encrypted keystore (or plaintext if no passphrase)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp_path = path + ".tmp"

        # Use O_CREAT | O_EXCL to avoid TOCTOU race on the temp file.
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                if passphrase:
                    keystore = Account.encrypt(self.__account.key, passphrase)
                    json.dump(keystore, f)
                else:
                    f.write(self.__account.key.hex() + "\n")
            os.replace(tmp_path, path)
        except BaseException:
            # Clean up .tmp on any write failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
