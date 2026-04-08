# Client Identity — Python SDK

The `ClientIdentity` class provides client-side wallet authentication for the SpaceRouter network. It manages secp256k1 keypairs, signs API requests, and supports encrypted keystore persistence.

## Installation

```bash
pip install spacerouter
```

The `eth-account` and `web3` dependencies are included by default.

## Quick Start

```python
from spacerouter import ClientIdentity, SpaceRouter

# Generate a new identity
identity = ClientIdentity.generate()
print(identity.address)  # 0x...

# Use with SpaceRouter client
with SpaceRouter(identity=identity) as client:
    response = client.get("https://httpbin.org/ip")
    print(response.json())
```

## API Reference

### `ClientIdentity`

Client-side identity wallet for wallet-authenticated requests. The private key is stored internally and never exposed as a string attribute.

> **Note:** Do not instantiate `ClientIdentity` directly. Use the class methods below.

---

#### `ClientIdentity.generate(keystore_path=None, passphrase="")`

Generate a new identity wallet with a random secp256k1 keypair.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `keystore_path` | `str \| None` | `None` | Path to save the keystore file |
| `passphrase` | `str` | `""` | Encryption passphrase (empty = plaintext) |

**Returns:** `ClientIdentity`

```python
# Generate without saving
identity = ClientIdentity.generate()

# Generate and save encrypted keystore
identity = ClientIdentity.generate(
    keystore_path="~/.spacerouter/identity.json",
    passphrase="my-secure-passphrase"
)

# Generate and save plaintext keystore
identity = ClientIdentity.generate(
    keystore_path="~/.spacerouter/identity.key"
)
```

---

#### `ClientIdentity.from_private_key(private_key)`

Create an identity from a raw hex private key.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `private_key` | `str` | Hex-encoded private key (with or without `0x` prefix) |

**Returns:** `ClientIdentity`

```python
identity = ClientIdentity.from_private_key("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
print(identity.address)
```

> **Security:** Avoid hardcoding private keys. Use keystores or environment variables.

---

#### `ClientIdentity.from_keystore(path, passphrase="")`

Load an identity from a Web3 encrypted keystore JSON file or a plaintext hex key file.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | *(required)* | Path to keystore file |
| `passphrase` | `str` | `""` | Decryption passphrase |

**Returns:** `ClientIdentity`

**Raises:**

- `ValueError` — If the keystore is encrypted and no passphrase is provided
- `FileNotFoundError` — If the file does not exist

```python
# Load from encrypted keystore
identity = ClientIdentity.from_keystore(
    "~/.spacerouter/identity.json",
    passphrase="my-secure-passphrase"
)

# Load from plaintext key file
identity = ClientIdentity.from_keystore("~/.spacerouter/identity.key")
```

---

#### `identity.address` *(property)*

The identity's Ethereum address (lowercase, `0x`-prefixed).

**Type:** `str`

```python
identity = ClientIdentity.generate()
print(identity.address)  # "0x1234...abcd"
```

---

#### `identity.payment_address` *(property)*

Optional payment wallet address. Set with the setter.

**Type:** `str | None`

```python
identity.payment_address = "0xabcd...1234"
print(identity.payment_address)  # "0xabcd...1234" (lowercased)
```

---

#### `identity.sign_message(message)`

Sign an arbitrary message using EIP-191 personal sign.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `message` | `str` | Message to sign |

**Returns:** `str` — `0x`-prefixed hex signature

```python
signature = identity.sign_message("hello world")
print(signature)  # "0x..." (65-byte EIP-191 signature)
```

---

#### `identity.sign_auth_header(timestamp=None)`

Generate authentication headers for Coordination API requests.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timestamp` | `int \| None` | `None` | Unix timestamp (auto-generated if `None`) |

**Returns:** `dict[str, str]` with keys:
- `X-Identity-Address` — The identity address
- `X-Identity-Signature` — EIP-191 signature of `space-router:auth:{address}:{timestamp}`
- `X-Timestamp` — Unix timestamp string

Server-side validation window is **±300 seconds**.

```python
headers = identity.sign_auth_header()
print(headers)
# {
#     "X-Identity-Address": "0x1234...abcd",
#     "X-Identity-Signature": "0x...",
#     "X-Timestamp": "1711828800"
# }
```

---

#### `identity.save_keystore(path, passphrase="")`

Export the identity to a keystore file. Encrypted (Web3 secret storage format) when a passphrase is provided, plaintext hex otherwise.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | *(required)* | Output file path |
| `passphrase` | `str` | `""` | Encryption passphrase (empty = plaintext) |

**Security features:**
- File permissions set to `0o600` (owner read/write only)
- Atomic writes via temp file + `os.replace()`
- Temp file cleanup on failure

```python
# Save encrypted
identity.save_keystore("/path/to/keystore.json", passphrase="strong-passphrase")

# Save plaintext
identity.save_keystore("/path/to/identity.key")
```

---

### Standalone Functions

These functions manage node-level identity keypairs (separate from client identity wallets).

#### `load_or_create_identity(key_path=DEFAULT_IDENTITY_PATH)`

Load or generate a secp256k1 node identity keypair. Default path: `~/.spacerouter/identity.key`.

**Returns:** `tuple[str, str]` — `(private_key_hex, address)`

```python
from spacerouter import load_or_create_identity

private_key, address = load_or_create_identity()
print(f"Node address: {address}")
```

#### `sign_request(private_key, action, target)`

Sign a SpaceRouter API request.

**Returns:** `tuple[str, int]` — `(signature_hex, timestamp)`

```python
from spacerouter import sign_request

signature, timestamp = sign_request(private_key, "register", node_id)
```

#### `create_vouching_signature(private_key, staking_address, collection_address)`

Sign a vouching message linking staking and collection wallets.

**Returns:** `tuple[str, int]` — `(signature_hex, timestamp)`

```python
from spacerouter import create_vouching_signature

sig, ts = create_vouching_signature(private_key, staking_addr, collection_addr)
```

---

## Using ClientIdentity with SpaceRouter

### Sync Client

```python
from spacerouter import ClientIdentity, SpaceRouter

identity = ClientIdentity.from_keystore("~/.spacerouter/identity.json", "pass")

with SpaceRouter(identity=identity) as client:
    response = client.get("https://httpbin.org/ip")
    print(response.json())
```

### Async Client

```python
from spacerouter import ClientIdentity, AsyncSpaceRouter

identity = ClientIdentity.from_keystore("~/.spacerouter/identity.json", "pass")

async with AsyncSpaceRouter(identity=identity) as client:
    response = await client.get("https://httpbin.org/ip")
    print(response.json())
```

### With Region Targeting

```python
identity = ClientIdentity.from_keystore("~/.spacerouter/identity.json", "pass")

with SpaceRouter(identity=identity, region="US") as client:
    us_response = client.get("https://httpbin.org/ip")

    kr_client = client.with_routing(region="KR")
    kr_response = kr_client.get("https://httpbin.org/ip")
```

---

## Keystore Format

### Encrypted Keystore (Web3 Secret Storage)

When a passphrase is provided, keystores use the [Web3 Secret Storage Definition](https://ethereum.org/en/developers/docs/data-structures-and-encoding/web3-secret-storage/):

```json
{
  "version": 3,
  "id": "...",
  "address": "1234...abcd",
  "crypto": {
    "cipher": "aes-128-ctr",
    "cipherparams": { "iv": "..." },
    "ciphertext": "...",
    "kdf": "scrypt",
    "kdfparams": {
      "dklen": 32,
      "n": 262144,
      "r": 8,
      "p": 1,
      "salt": "..."
    },
    "mac": "..."
  }
}
```

### Plaintext Key File

Without a passphrase, the key is stored as a raw hex string:

```
0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
```

> **Warning:** Plaintext key files should only be used in development. Always use encrypted keystores in production.

---

## WalletManager Pattern

For applications managing multiple identities:

```python
from spacerouter import ClientIdentity

class WalletManager:
    def __init__(self, keystore_dir: str = "~/.spacerouter/wallets"):
        self.keystore_dir = keystore_dir
        self._identities: dict[str, ClientIdentity] = {}

    def create(self, name: str, passphrase: str) -> ClientIdentity:
        path = f"{self.keystore_dir}/{name}.json"
        identity = ClientIdentity.generate(keystore_path=path, passphrase=passphrase)
        self._identities[name] = identity
        return identity

    def load(self, name: str, passphrase: str) -> ClientIdentity:
        path = f"{self.keystore_dir}/{name}.json"
        identity = ClientIdentity.from_keystore(path, passphrase)
        self._identities[name] = identity
        return identity

    def get(self, name: str) -> ClientIdentity | None:
        return self._identities.get(name)
```
