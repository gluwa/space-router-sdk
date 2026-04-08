# SpaceRouter SDK

Client libraries and CLI for the [SpaceRouter](https://spacerouter.org) residential proxy network.

## Packages

| Package | Language | Registry | Description |
|---|---|---|---|
| [`spacerouter`](sdk/python/) | Python | [PyPI](https://pypi.org/project/spacerouter/) | Python SDK — proxy client + admin API |
| [`@spacenetwork/spacerouter`](sdk/js/) | TypeScript | [npm](https://www.npmjs.com/package/@spacenetwork/spacerouter) | JavaScript SDK — proxy client + admin API |
| [`spacerouter-cli`](cli/) | Python | [PyPI](https://pypi.org/project/spacerouter-cli/) | CLI for AI agents and developers |

## Quick start

### Python SDK

```bash
pip install spacerouter
```

```python
from spacerouter import SpaceRouter

async with SpaceRouter(api_key="sr_...") as client:
    response = await client.get("https://httpbin.org/ip")
    print(response.text)
```

### JavaScript SDK

```bash
npm install @spacenetwork/spacerouter
```

```typescript
import { SpaceRouter } from "@spacenetwork/spacerouter";

const client = new SpaceRouter({ apiKey: "sr_..." });
const response = await client.get("https://httpbin.org/ip");
console.log(response.body);
```

### CLI

```bash
pip install spacerouter-cli
spacerouter config set api-key sr_...
spacerouter request get https://httpbin.org/ip
```

## Client Identity

All packages support wallet-based authentication as an alternative to API keys. See the [Security Guide](docs/security.md) for key storage best practices.

```python
# Python
from spacerouter import ClientIdentity, SpaceRouter
identity = ClientIdentity.from_keystore("~/.spacerouter/identity.json", "passphrase")
with SpaceRouter(identity=identity) as client:
    response = client.get("https://httpbin.org/ip")
```

```typescript
// JavaScript
import { ClientIdentity, SpaceRouter } from "@spacenetwork/spacerouter";
const identity = ClientIdentity.fromKeystore("~/.spacerouter/identity.json", "passphrase");
const client = new SpaceRouter({ identity });
const response = await client.get("https://httpbin.org/ip");
```

```bash
# CLI
spacerouter identity generate --passphrase
spacerouter identity show --passphrase
```

## Development

```bash
# Python SDK
cd sdk/python && pip install -e ".[dev]" && pytest tests/ -v

# JavaScript SDK
cd sdk/js && npm install && npm test

# CLI (requires Python SDK installed first)
cd cli && pip install -e ".[dev]" && pytest tests/ -v
```

## API contract

These packages communicate with the SpaceRouter Proxy Gateway over HTTP/SOCKS5.

## Skills

The `skills/` directory contains Claude Code skills for AI agents to use SpaceRouter. Copy them to your `~/.claude/commands/` directory.

## License

MIT
