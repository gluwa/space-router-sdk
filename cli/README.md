# SpaceRouter CLI

CLI for the [Space Router](../README.md) residential proxy network. Designed for AI agents with JSON-first output.

## Installation

```bash
pip install spacerouter-cli
```

## Quick Start

```bash
# Set your API key
spacerouter config set api-key sr_live_YOUR_API_KEY

# Make a proxied request
spacerouter request get https://httpbin.org/ip

# Check service health
spacerouter status
```

## Identity Wallet

Manage client identity wallets for wallet-based authentication:

```bash
# Generate a new encrypted identity
spacerouter identity generate --passphrase
# Enter passphrase: ****
# Repeat for confirmation: ****
# {"status": "created", "address": "0x...", "keystore_path": "...", "encrypted": true}

# Show identity address
spacerouter identity show --passphrase
# {"address": "0x...", "keystore_path": "..."}

# Export to a new encrypted keystore
spacerouter identity export --output /path/to/backup.json --passphrase
# {"status": "exported", "address": "0x...", "output_path": "...", "encrypted": true}
```

See [docs/cli.md](docs/cli.md) for full command reference and the [Security Guide](../docs/security.md) for key storage best practices.

## Commands

| Command | Description |
|---|---|
| `spacerouter request` | Make proxied HTTP requests |
| `spacerouter api-key` | Manage API keys |
| `spacerouter node` | Manage proxy nodes |
| `spacerouter billing` | Billing and checkout |
| `spacerouter dashboard` | Dashboard data |
| `spacerouter config` | Configuration management |
| `spacerouter identity` | Identity wallet management |
| `spacerouter status` | Check service health |

All commands output JSON for easy parsing by AI agents and scripts.

## Development

```bash
# Install Python SDK first
cd ../sdk/python && pip install -e ".[dev]"

# Install CLI in development mode
cd ../cli && pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```
