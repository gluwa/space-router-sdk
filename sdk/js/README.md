# SpaceRouter JavaScript SDK

JavaScript/TypeScript SDK for routing HTTP requests through the [Space Router](../../README.md) residential proxy network.

## Installation

```bash
npm install @spacenetwork/spacerouter
```

## Quick Start

```ts
import { SpaceRouter } from "@spacenetwork/spacerouter";

const client = new SpaceRouter("sr_live_YOUR_API_KEY", {
  gatewayUrl: "http://gateway:8080",
});

const response = await client.get("https://httpbin.org/ip");
console.log(await response.json()); // { origin: "residential-ip" }
console.log(response.nodeId);       // node that handled the request
console.log(response.requestId);    // unique request ID for tracing

client.close();
```

## Region Targeting

Route requests through specific geographic regions:

```ts
// Target residential IPs in the US
const client = new SpaceRouter("sr_live_xxx", {
  region: "US",
});

// Target residential IPs in South Korea
const krClient = new SpaceRouter("sr_live_xxx", {
  region: "KR",
});

// Change routing on the fly
const jpClient = client.withRouting({ region: "JP" });
```

## SOCKS5 Proxy

```ts
const client = new SpaceRouter("sr_live_xxx", {
  protocol: "socks5",
  gatewayUrl: "socks5://gateway:1080",
});

const response = await client.get("https://httpbin.org/ip");
```

## API Key Management

```ts
import { SpaceRouterAdmin } from "@spacenetwork/spacerouter";

const admin = new SpaceRouterAdmin("http://localhost:8000");

// Create a key (raw value only available here)
const key = await admin.createApiKey("my-agent", { rateLimitRpm: 120 });
console.log(key.api_key); // sr_live_...

// List keys
const keys = await admin.listApiKeys();
for (const k of keys) {
  console.log(k.name, k.key_prefix, k.is_active);
}

// Revoke a key
await admin.revokeApiKey(key.id);
```

## Error Handling

```ts
import { SpaceRouter } from "@spacenetwork/spacerouter";
import {
  AuthenticationError,   // 407 - invalid API key
  RateLimitError,        // 429 - rate limit exceeded
  NoNodesAvailableError, // 503 - no residential nodes online
  UpstreamError,         // 502 - target unreachable via node
} from "@spacenetwork/spacerouter";

const client = new SpaceRouter("sr_live_xxx");
try {
  const response = await client.get("https://example.com");
} catch (e) {
  if (e instanceof RateLimitError) {
    console.log(`Rate limited, retry after ${e.retryAfter}s`);
  } else if (e instanceof NoNodesAvailableError) {
    console.log("No nodes available, try again later");
  } else if (e instanceof UpstreamError) {
    console.log(`Node ${e.nodeId} could not reach target`);
  } else if (e instanceof AuthenticationError) {
    console.log("Check your API key");
  }
}
```

Note: HTTP errors from the target website (e.g. 404, 500) are **not** thrown as exceptions. Only proxy-layer errors produce exceptions.

## Client Identity (Wallet Authentication)

As an alternative to API keys, you can authenticate using a client identity wallet:

```ts
import { ClientIdentity, SpaceRouter } from "@spacenetwork/spacerouter";

// Generate a new identity
const identity = ClientIdentity.generate();
console.log(identity.address); // 0x...

// Save with encryption
identity.saveKeystore("~/.spacerouter/identity.json", "my-secure-passphrase");

// Load an existing identity
const loaded = ClientIdentity.fromKeystore(
  "~/.spacerouter/identity.json",
  "my-secure-passphrase"
);

// Use with SpaceRouter client
const client = new SpaceRouter({ identity: loaded });
const response = await client.get("https://httpbin.org/ip");
console.log(await response.json());
client.close();
```

### Identity Methods

```ts
// Sign arbitrary messages (EIP-191)
const signature = await identity.signMessage("hello world");

// Generate auth headers for Coordination API
const headers = await identity.signAuthHeaders();
// { "X-Identity-Address": "0x...", "X-Identity-Signature": "0x...", "X-Timestamp": "..." }

// Export to encrypted keystore
identity.saveKeystore("/path/to/backup.json", "backup-pass");
```

See [docs/identity.md](docs/identity.md) for the full API reference and [docs/security.md](../../docs/security.md) for key storage best practices.

## Configuration

| Parameter    | Default                    | Description                              |
|-------------|----------------------------|------------------------------------------|
| `apiKey`    | (required)                 | API key (`sr_live_...`)                  |
| `gatewayUrl`| `"http://localhost:8080"`  | Proxy gateway URL                        |
| `protocol`  | `"http"`                   | `"http"` or `"socks5"`                   |
| `region`    | `undefined`                | 2-letter country code (ISO 3166-1 alpha-2) |
| `timeout`   | `30000`                    | Request timeout in milliseconds          |
