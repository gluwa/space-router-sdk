# Space Router SDK

Client libraries and CLI for the [Space Router](https://github.com/gluwa/space-router) residential proxy network.

## Packages

| Package | Language | Registry | Description |
|---|---|---|---|
| [`spacerouter`](sdk/python/) | Python | [PyPI](https://pypi.org/project/spacerouter/) | Python SDK — proxy client + admin API |
| [`spacerouter`](sdk/js/) | TypeScript | [npm](https://www.npmjs.com/package/spacerouter) | JavaScript SDK — proxy client + admin API |
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
npm install spacerouter
```

```typescript
import { SpaceRouter } from "spacerouter";

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

These packages communicate with the Space Router Proxy Gateway over HTTP/SOCKS5. See [component-contracts.md](https://github.com/gluwa/space-router/blob/main/docs/component-contracts.md) for full specifications.

## Skills

The `skills/` directory contains Claude Code skills for AI agents to use Space Router. Copy them to your `~/.claude/commands/` directory.

## License

MIT
