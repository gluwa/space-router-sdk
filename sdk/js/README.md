# SpaceRouter JavaScript SDK

JavaScript/TypeScript SDK for routing HTTP requests through the [Space Router](../../README.md) residential proxy network.

## Installation

```bash
npm install @spacenetwork/spacerouter
```

## Quick Start

```ts
import { SpaceRouter } from "@spacenetwork/spacerouter";
import { SpaceRouterSPACE } from "@spacenetwork/spacerouter/payment";

// Two URLs, two purposes — see "gatewayUrl vs gatewayManagementUrl" below.
const GATEWAY_URL            = "https://gateway.example.com";        // proxy CONNECT (:443/:8080)
const GATEWAY_MANAGEMENT_URL = "https://gateway.example.com:8081";   // /auth/challenge + /leg1/*

const client = new SpaceRouter("sr_live_YOUR_API_KEY", {
  gatewayUrl: GATEWAY_URL,
});

// Escrow-payment consumers also wire up the management endpoint:
const space = new SpaceRouterSPACE({
  gatewayMgmtUrl: GATEWAY_MANAGEMENT_URL,
  wallet,            // your ClientPaymentWallet
});

const response = await client.get("https://httpbin.org/ip");
console.log(await response.json()); // { origin: "residential-ip" }
console.log(response.nodeId);       // node that handled the request
console.log(response.requestId);    // unique request ID for tracing

client.close();
```

### `gatewayUrl` vs `gatewayManagementUrl`

Two listeners on the *same* gateway server:

* `gatewayUrl` (passed to `SpaceRouter`) is the **proxy** endpoint —
  typically port 443 or 8080. It only handles `CONNECT` for tunnelled
  application traffic.
* `gatewayMgmtUrl` (passed to `SpaceRouterSPACE`, conceptually the
  same as `gatewayManagementUrl`) is the **management API** endpoint —
  typically port 8081. It serves `/auth/challenge` and `/leg1/...`.

Sending management requests to the proxy port returns **HTTP 407**
because the proxy listener only answers `CONNECT`. See the
troubleshooting section below.

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

## Self-signed certificates / dev environments

When developing against a test gateway with a self-signed TLS certificate
(`SELF_SIGNED_CERT_IN_CHAIN`), pass `verify: false`:

```ts
const client = new SpaceRouter("sr_test_xxx", {
  gatewayUrl: "https://gateway.test.spacerouter.org",
  verify: false, // dev only — skips TLS cert verification
});
```

> Set to `false` to skip TLS certificate verification for the gateway
> connection. Use only for development against a test gateway with a
> self-signed certificate. Default `true`.

If you're running the SDK behind a wrapper that doesn't expose this
option, set the environment variable instead:

```bash
NODE_TLS_REJECT_UNAUTHORIZED=0 node my-app.js
```

The `verify` option currently applies to the HTTPS gateway path only.
SOCKS5 users on a self-signed gateway should use the env-var fallback.

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

## Troubleshooting

### If you get HTTP 407, you probably swapped `proxy_url` and `gateway_url`

`HTTP 407 Proxy Authentication Required` on a management call (e.g.
`SpaceRouterSPACE.requestChallenge()` or any `/auth/challenge` /
`/leg1/...` request) almost always means you pointed `gatewayMgmtUrl`
at the **proxy** listener instead of the **management** listener.

The proxy port (typically `:443` or `:8080`) only handles `CONNECT` —
every other verb is answered with 407. The management API
(`/auth/challenge`, `/leg1/...`) lives on a different port (typically
`:8081`) on the same gateway host.

Fix:

```ts
// Wrong — both URLs point at the proxy port:
new SpaceRouterSPACE({ gatewayMgmtUrl: "https://gateway.example.com" });
//                                      ^^^ proxy port — returns 407 on /auth/challenge

// Right — management URL is the :8081 listener:
new SpaceRouterSPACE({ gatewayMgmtUrl: "https://gateway.example.com:8081" });
```

If your deployment exposes both proxy and management on the same port
(some single-port gateways do), set both to the same URL. Otherwise
keep them split.

## Configuration

| Parameter    | Default                    | Description                              |
|-------------|----------------------------|------------------------------------------|
| `apiKey`    | (required)                 | API key (`sr_live_...`)                  |
| `gatewayUrl`| `"http://localhost:8080"`  | Proxy gateway URL                        |
| `protocol`  | `"http"`                   | `"http"` or `"socks5"`                   |
| `region`    | `undefined`                | 2-letter country code (ISO 3166-1 alpha-2) |
| `timeout`   | `30000`                    | Request timeout in milliseconds          |
| `verify`    | `true`                     | TLS cert verification for gateway connection (HTTPS path) |
