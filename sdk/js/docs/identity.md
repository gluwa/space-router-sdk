# Client Identity — JavaScript SDK

The `ClientIdentity` class provides client-side wallet authentication for the SpaceRouter network. It manages secp256k1 keypairs, signs API requests, and supports encrypted keystore persistence using the Web3 Secret Storage format.

## Installation

```bash
npm install @spacenetwork/spacerouter
```

## Quick Start

```ts
import { ClientIdentity, SpaceRouter } from "@spacenetwork/spacerouter";

// Generate a new identity
const identity = ClientIdentity.generate();
console.log(identity.address); // 0x...

// Use with SpaceRouter client
const client = new SpaceRouter({ identity });
const response = await client.get("https://httpbin.org/ip");
console.log(await response.json());
client.close();
```

## API Reference

### `ClientIdentity`

Client-side identity wallet for wallet-authenticated requests. The private key is stored as an ES2022 private class field (`#privateKey`) and is inaccessible from outside the class — it cannot be leaked via `Object.keys()`, `JSON.stringify()`, or property enumeration.

> **Note:** The constructor is private. Use the static factory methods below.

---

#### `ClientIdentity.fromPrivateKey(privateKey)`

Create an identity from a raw hex private key.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `privateKey` | `` `0x${string}` `` | Hex-encoded private key with `0x` prefix |

**Returns:** `ClientIdentity`

```ts
const identity = ClientIdentity.fromPrivateKey(
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
);
console.log(identity.address);
```

> **Security:** Avoid hardcoding private keys. Use keystores or environment variables.

---

#### `ClientIdentity.generate(keystorePath?)`

Generate a new identity wallet with a random secp256k1 keypair.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `keystorePath` | `string` | `undefined` | Path to save the keystore file (plaintext) |

**Returns:** `ClientIdentity`

```ts
// Generate without saving
const identity = ClientIdentity.generate();

// Generate and save to disk
const identity = ClientIdentity.generate("~/.spacerouter/identity.key");
```

---

#### `ClientIdentity.fromKeystore(path, passphrase?)`

Load an identity from a Web3 encrypted keystore JSON file or a plaintext hex key file.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `string` | *(required)* | Path to keystore file |
| `passphrase` | `string` | `undefined` | Decryption passphrase |

**Returns:** `ClientIdentity`

**Throws:**

- `Error` — If the keystore is encrypted and no passphrase is provided
- `Error` — Wrong passphrase (MAC mismatch)

```ts
// Load from encrypted keystore
const identity = ClientIdentity.fromKeystore(
  "~/.spacerouter/identity.json",
  "my-secure-passphrase"
);

// Load from plaintext key file
const identity = ClientIdentity.fromKeystore("~/.spacerouter/identity.key");
```

**Encryption details:** The JS SDK implements its own scrypt + aes-128-ctr decryption using Node.js `crypto` module, following the Web3 Secret Storage Definition. MAC verification uses SHA3-256 (Keccak).

---

#### `identity.address` *(getter)*

The identity's Ethereum address (lowercase, `0x`-prefixed).

**Type:** `string`

```ts
console.log(identity.address); // "0x1234...abcd"
```

---

#### `identity.paymentAddress` *(getter/setter)*

Optional payment wallet address.

**Type:** `string | undefined`

```ts
identity.paymentAddress = "0xabcd...1234";
console.log(identity.paymentAddress); // "0xabcd...1234" (lowercased)
```

---

#### `identity.signMessage(message)`

Sign an arbitrary message using EIP-191 personal sign (via viem).

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `message` | `string` | Message to sign |

**Returns:** `Promise<string>` — Hex signature

```ts
const signature = await identity.signMessage("hello world");
console.log(signature); // "0x..." (65-byte EIP-191 signature)
```

---

#### `identity.signAuthHeaders(timestamp?)`

Generate authentication headers for Coordination API requests.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timestamp` | `number` | `undefined` | Unix timestamp (auto-generated if omitted) |

**Returns:** `Promise<Record<string, string>>` with keys:
- `X-Identity-Address` — The identity address
- `X-Identity-Signature` — EIP-191 signature of `space-router:auth:{address}:{timestamp}`
- `X-Timestamp` — Unix timestamp string

**Throws:** `TypeError` — If timestamp is not a finite number

Server-side validation window is **±300 seconds**.

```ts
const headers = await identity.signAuthHeaders();
console.log(headers);
// {
//   "X-Identity-Address": "0x1234...abcd",
//   "X-Identity-Signature": "0x...",
//   "X-Timestamp": "1711828800"
// }
```

---

#### `identity.saveKeystore(path, passphrase?)`

Export the identity to a keystore file. When a passphrase is provided, encrypts using Web3 secret storage format (scrypt + aes-128-ctr). Otherwise saves as plaintext hex.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `string` | *(required)* | Output file path |
| `passphrase` | `string` | `undefined` | Encryption passphrase |

**Security features:**
- File permissions set to `0o600` (owner read/write only)
- Parent directories created automatically

```ts
// Save encrypted
identity.saveKeystore("/path/to/keystore.json", "strong-passphrase");

// Save plaintext
identity.saveKeystore("/path/to/identity.key");
```

---

### Standalone Functions

These functions manage node-level identity keypairs (separate from client identity wallets).

#### `loadOrCreateIdentity(keyPath?)`

Load or generate a secp256k1 node identity keypair. Default path: `~/.spacerouter/identity.key`.

**Returns:** `{ privateKey: \`0x${string}\`, address: string }`

```ts
import { loadOrCreateIdentity } from "@spacenetwork/spacerouter";

const { privateKey, address } = loadOrCreateIdentity();
console.log(`Node address: ${address}`);
```

#### `signRequest(privateKey, action, target)`

Sign a SpaceRouter API request (async, EIP-191).

**Returns:** `Promise<{ signature: string, timestamp: number }>`

```ts
import { signRequest } from "@spacenetwork/spacerouter";

const { signature, timestamp } = await signRequest(privateKey, "register", nodeId);
```

#### `createVouchingSignature(privateKey, stakingAddress, collectionAddress)`

Sign a vouching message linking staking and collection wallets.

**Returns:** `Promise<{ signature: string, timestamp: number }>`

```ts
import { createVouchingSignature } from "@spacenetwork/spacerouter";

const { signature, timestamp } = await createVouchingSignature(
  privateKey, stakingAddr, collectionAddr
);
```

---

## Using ClientIdentity with SpaceRouter

### Basic Usage

```ts
import { ClientIdentity, SpaceRouter } from "@spacenetwork/spacerouter";

const identity = ClientIdentity.fromKeystore(
  "~/.spacerouter/identity.json",
  "passphrase"
);

const client = new SpaceRouter({ identity });
const response = await client.get("https://httpbin.org/ip");
console.log(await response.json());
client.close();
```

### With Region Targeting

```ts
const client = new SpaceRouter({
  identity,
  region: "US",
});

const usResponse = await client.get("https://httpbin.org/ip");

// Switch region
const jpClient = client.withRouting({ region: "JP" });
const jpResponse = await jpClient.get("https://httpbin.org/ip");
```

---

## Keystore Format

### Encrypted Keystore (Web3 Secret Storage)

When a passphrase is provided, keystores follow the [Web3 Secret Storage Definition](https://ethereum.org/en/developers/docs/data-structures-and-encoding/web3-secret-storage/):

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

**Encryption parameters:**
- **KDF:** scrypt (N=262144, r=8, p=1, dklen=32)
- **Cipher:** AES-128-CTR
- **MAC:** SHA3-256 (Keccak) over derived key bytes [16:32] + ciphertext
- **Salt/IV:** Cryptographically random (32 bytes / 16 bytes)

### Plaintext Key File

Without a passphrase, the key is stored as a raw hex string:

```
0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
```

> **Warning:** Plaintext key files should only be used in development. Always use encrypted keystores in production.

---

## Python ↔ JS Keystore Compatibility

Encrypted keystores are **fully compatible** between the Python and JavaScript SDKs. A keystore created by the Python SDK can be loaded by the JS SDK and vice versa — both implement the standard Web3 Secret Storage format.

```python
# Python: create encrypted keystore
identity = ClientIdentity.generate(
    keystore_path="shared.json",
    passphrase="cross-sdk"
)
```

```ts
// JavaScript: load the same keystore
const identity = ClientIdentity.fromKeystore("shared.json", "cross-sdk");
console.log(identity.address); // Same address as Python
```
