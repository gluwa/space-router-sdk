# SpaceRouter CLI Reference

## Identity Commands

The `identity` command group manages client identity wallets for wallet-based authentication.

### `spacerouter identity generate`

Generate a new identity wallet and save it to a keystore file.

```bash
# Generate with default path (~/.spacerouter/identity.json)
spacerouter identity generate

# Generate with custom path
spacerouter identity generate --keystore-path /path/to/keystore.json

# Generate with passphrase encryption
spacerouter identity generate --passphrase
# Enter passphrase: ****
# Repeat for confirmation: ****
```

**Options:**

| Option | Short | Default | Description |
|---|---|---|---|
| `--keystore-path` | `-k` | `~/.spacerouter/identity.json` | Path to save the identity keystore |
| `--passphrase` | `-p` | `false` | Prompt for encryption passphrase |

**Output (JSON):**

```json
{
  "status": "created",
  "address": "0x1234567890abcdef1234567890abcdef12345678",
  "keystore_path": "/home/user/.spacerouter/identity.json",
  "encrypted": true
}
```

**Error — file already exists:**

```json
{
  "error": "File already exists: /home/user/.spacerouter/identity.json"
}
```

> **Note:** The `generate` command refuses to overwrite existing keystore files. Delete the existing file first or choose a different path.

---

### `spacerouter identity show`

Display the identity address from an existing keystore file.

```bash
# Show address from default keystore
spacerouter identity show

# Show from custom path
spacerouter identity show --keystore-path /path/to/keystore.json

# Show from encrypted keystore
spacerouter identity show --passphrase
# Enter passphrase: ****
```

**Options:**

| Option | Short | Default | Description |
|---|---|---|---|
| `--keystore-path` | `-k` | `~/.spacerouter/identity.json` | Path to the identity keystore |
| `--passphrase` | `-p` | `false` | Prompt for passphrase (required for encrypted keystores) |

**Output (JSON):**

```json
{
  "address": "0x1234567890abcdef1234567890abcdef12345678",
  "keystore_path": "/home/user/.spacerouter/identity.json"
}
```

**Error — keystore not found:**

```json
{
  "error": "Keystore not found: /home/user/.spacerouter/identity.json"
}
```

**Error — encrypted keystore without passphrase:**

```json
{
  "error": "Keystore at '/home/user/.spacerouter/identity.json' is encrypted — passphrase required."
}
```

---

### `spacerouter identity export`

Export an identity to a new keystore file, optionally re-encrypting with a different passphrase.

```bash
# Export to a new encrypted keystore
spacerouter identity export --output /path/to/exported.json
# Enter export passphrase: ****
# Repeat for confirmation: ****

# Export from encrypted source
spacerouter identity export --passphrase --output /path/to/exported.json
# Enter source passphrase: ****
# Enter export passphrase: ****
# Repeat for confirmation: ****

# Export as plaintext (not recommended for production)
spacerouter identity export --output /path/to/exported.key --no-encrypt
```

**Options:**

| Option | Short | Default | Description |
|---|---|---|---|
| `--keystore-path` | `-k` | `~/.spacerouter/identity.json` | Path to the source identity keystore |
| `--output` | `-o` | *(required)* | Output path for the exported keystore |
| `--passphrase` | `-p` | `false` | Prompt for source keystore passphrase |
| `--encrypt / --no-encrypt` | | `--encrypt` | Encrypt the exported keystore |

**Output (JSON):**

```json
{
  "status": "exported",
  "address": "0x1234567890abcdef1234567890abcdef12345678",
  "output_path": "/path/to/exported.json",
  "encrypted": true
}
```

---

## Encrypted Keystore Workflow

### Initial Setup

```bash
# 1. Generate a new encrypted identity
spacerouter identity generate --passphrase

# 2. Verify the identity was created
spacerouter identity show --passphrase

# 3. Create an encrypted backup
spacerouter identity export \
  --passphrase \
  --output ~/.spacerouter/identity-backup.json
```

### Migrating from Plaintext to Encrypted

```bash
# Export existing plaintext key to encrypted keystore
spacerouter identity export \
  --keystore-path ~/.spacerouter/identity.key \
  --output ~/.spacerouter/identity.json

# Verify the new encrypted keystore
spacerouter identity show \
  --keystore-path ~/.spacerouter/identity.json \
  --passphrase

# Remove the old plaintext file
rm ~/.spacerouter/identity.key
```

### Using Identity with Other Commands

The identity wallet is used by the Python SDK when making authenticated requests:

```python
from spacerouter import ClientIdentity, SpaceRouter

identity = ClientIdentity.from_keystore("~/.spacerouter/identity.json", "pass")
with SpaceRouter(identity=identity) as client:
    response = client.get("https://httpbin.org/ip")
```

---

## All Commands

| Command | Description |
|---|---|
| `spacerouter request get\|post\|...` | Make proxied HTTP requests |
| `spacerouter api-key create\|list\|revoke` | Manage API keys |
| `spacerouter node register\|list\|...` | Manage proxy nodes |
| `spacerouter billing ...` | Billing and checkout |
| `spacerouter dashboard ...` | Dashboard data |
| `spacerouter config set\|get\|...` | Configuration management |
| `spacerouter identity generate\|show\|export` | Identity wallet management |
| `spacerouter status` | Check service health |
| `spacerouter --version` | Show CLI version |

All commands output JSON for AI-agent consumption.
