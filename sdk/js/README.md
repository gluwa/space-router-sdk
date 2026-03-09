# SpaceRouter JavaScript SDK

JavaScript/TypeScript SDK for routing HTTP requests through the [Space Router](../../README.md) residential proxy network.

## Installation

```bash
npm install spacerouter
```

## Quick Start

```ts
import { SpaceRouter } from "spacerouter";

const client = new SpaceRouter("sr_live_YOUR_API_KEY", {
  gatewayUrl: "http://gateway:8080",
});

const response = await client.get("https://httpbin.org/ip");
console.log(await response.json()); // { origin: "residential-ip" }
console.log(response.nodeId);       // node that handled the request
console.log(response.requestId);    // unique request ID for tracing

client.close();
```

## IP Targeting

Route requests through specific IP types or geographic regions:

```ts
// Target residential IPs in the US
const client = new SpaceRouter("sr_live_xxx", {
  ipType: "residential",
  region: "US",
});

// Target mobile IPs in South Korea
const mobile = new SpaceRouter("sr_live_xxx", {
  ipType: "mobile",
  region: "Seoul, KR",
});

// Change routing on the fly
const jpClient = client.withRouting({ ipType: "mobile", region: "JP" });
```

Available IP types: `residential`, `mobile`, `datacenter`, `business`

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
import { SpaceRouterAdmin } from "spacerouter";

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
import { SpaceRouter } from "spacerouter";
import {
  AuthenticationError,   // 407 - invalid API key
  RateLimitError,        // 429 - rate limit exceeded
  NoNodesAvailableError, // 503 - no residential nodes online
  UpstreamError,         // 502 - target unreachable via node
} from "spacerouter";

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

## Configuration

| Parameter    | Default                    | Description                              |
|-------------|----------------------------|------------------------------------------|
| `apiKey`    | (required)                 | API key (`sr_live_...`)                  |
| `gatewayUrl`| `"http://localhost:8080"`  | Proxy gateway URL                        |
| `protocol`  | `"http"`                   | `"http"` or `"socks5"`                   |
| `ipType`    | `undefined`                | IP type filter                           |
| `region`    | `undefined`                | Region filter (substring match)          |
| `timeout`   | `30000`                    | Request timeout in milliseconds          |
