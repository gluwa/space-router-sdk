"""Node identity keypair management for the SpaceRouter SDK.

Generates and persists a secp256k1 keypair used for signing authenticated
API requests.  Default storage: ``~/.spacerouter/identity.key``.
"""

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
