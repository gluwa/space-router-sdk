# Security Guide

This document covers key storage, encryption, signature verification, and security best practices for the SpaceRouter SDK identity system.

## Overview

The SpaceRouter client identity system uses **secp256k1 keypairs** (the same curve as Ethereum) for wallet-based authentication. The private key signs API requests; the Coordination API verifies signatures against the registered public address.

## Key Storage

### Encrypted Keystores (Recommended)

Both Python and JavaScript SDKs support the [Web3 Secret Storage Definition](https://ethereum.org/en/developers/docs/data-structures-and-encoding/web3-secret-storage/) for encrypted key storage.

**Encryption parameters:**

| Parameter | Value | Purpose |
|---|---|---|
| KDF | scrypt | Password-based key derivation |
| N | 262,144 | CPU/memory cost (2^18) |
| r | 8 | Block size |
| p | 1 | Parallelization |
| dklen | 32 | Derived key length (bytes) |
| Cipher | AES-128-CTR | Symmetric encryption |
| MAC | SHA3-256 (Keccak) | Integrity verification |

**Creating an encrypted keystore:**

```python
# Python
identity = ClientIdentity.generate(
    keystore_path="~/.spacerouter/identity.json",
    passphrase="strong-passphrase-here"
)
```

```ts
// JavaScript
const identity = ClientIdentity.generate();
identity.saveKeystore("~/.spacerouter/identity.json", "strong-passphrase-here");
```

```bash
# CLI
spacerouter identity generate --passphrase
# Prompts: Enter passphrase: ****
# Prompts: Repeat for confirmation: ****
```

### Plaintext Key Files (Development Only)

Without a passphrase, the private key is stored as a hex string. **Use only in development or testing environments.**

### File Permissions

All keystore writes enforce `0o600` (owner read/write only):

- **Python:** `os.chmod(path, 0o600)` after write
- **JavaScript:** `writeFileSync(path, data, { mode: 0o600 })` + `chmodSync(path, 0o600)`
- **CLI:** Inherits from Python SDK

> **Verify permissions:** `ls -la ~/.spacerouter/identity.json` should show `-rw-------`.

### Atomic Writes

The Python SDK uses atomic file writes to prevent keystore corruption:

1. Write to `{path}.tmp` using `O_CREAT | O_EXCL` (prevents TOCTOU race)
2. Set permissions on temp file
3. `os.replace()` atomically moves temp → final path
4. On failure, temp file is cleaned up

## Private Key Protection

### Python SDK

The private key is stored as an `eth_account.Account` object using Python name mangling (`__account`). The key is never stored as a string attribute:

```python
identity = ClientIdentity.from_private_key("0x...")
# identity.__account → AttributeError
# identity._ClientIdentity__account → accessible only via mangled name
# No key string stored — only the Account object
```

### JavaScript SDK

The private key uses an ES2022 private class field (`#privateKey`), providing true runtime encapsulation:

```ts
const identity = ClientIdentity.fromPrivateKey("0x...");
// identity.#privateKey → SyntaxError (inaccessible outside class)
// Object.keys(identity) → does not include #privateKey
// JSON.stringify(identity) → does not include #privateKey
```

## Signature Verification

### Auth Header Signature Format

The `sign_auth_header()` / `signAuthHeaders()` method produces EIP-191 signatures over:

```
space-router:auth:{address}:{timestamp}
```

**Server-side verification:**

1. Extract `X-Identity-Address`, `X-Identity-Signature`, `X-Timestamp` headers
2. Verify timestamp is within ±300 seconds of server time
3. Reconstruct the message: `space-router:auth:{address}:{timestamp}`
4. Recover the signer address from the EIP-191 signature
5. Confirm recovered address matches `X-Identity-Address`

### Vouching Signature Format

```
space-router:vouch:{staking_address}:{collection_address}:{timestamp}
```

### Request Signature Format

```
space-router:{action}:{target}:{timestamp}
```

## Passphrase Handling

### Best Practices

1. **Never hardcode passphrases** in source code
2. **Use environment variables** or secret managers for automated deployments:
   ```python
   import os
   passphrase = os.environ["SPACEROUTER_KEYSTORE_PASSPHRASE"]
   identity = ClientIdentity.from_keystore("keystore.json", passphrase)
   ```
3. **Use the CLI's interactive prompt** for manual operations:
   ```bash
   spacerouter identity generate --passphrase
   # Secure interactive prompt — passphrase is not echoed
   ```
4. **Use strong passphrases** — the scrypt KDF provides brute-force resistance, but weak passphrases remain vulnerable to dictionary attacks

### CLI Passphrase Prompts

The CLI uses `typer.prompt(hide_input=True)` for secure passphrase input:

- Input is not echoed to the terminal
- `generate` and `export` require confirmation (enter passphrase twice)
- `show` requires single entry (no confirmation needed)

## Deployment Recommendations

### Production

- Always use encrypted keystores
- Store passphrases in a secret manager (e.g., AWS Secrets Manager, HashiCorp Vault)
- Set file permissions to `0o600`
- Restrict file access to the application service account
- Rotate identity keys periodically
- Monitor for unauthorized key file access via file audit logs

### Development

- Plaintext keystores are acceptable for local development
- Use separate identity keys for dev/staging/production
- Never commit keystore files to version control

### CI/CD

```bash
# Example: load passphrase from environment
export SPACEROUTER_PASSPHRASE=$(vault kv get -field=passphrase secret/spacerouter)
spacerouter identity show --keystore-path /run/secrets/identity.json --passphrase
```

## Threat Model

| Threat | Mitigation |
|---|---|
| Key file stolen from disk | Encrypted keystore requires passphrase to decrypt |
| Key leaked via serialization | Private fields prevent `JSON.stringify` / `repr()` exposure |
| Partial keystore write (crash) | Atomic writes via temp file + rename |
| TOCTOU race on temp file | `O_CREAT \| O_EXCL` flags (Python) |
| Replay attacks | Timestamp validation window (±300s) |
| Weak passphrase | scrypt KDF with high work factor (N=262144) |
| Permission escalation | File permissions `0o600` on keystore files |
