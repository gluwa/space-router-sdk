# E2E Testing

## E2E Demo (Automated)

The fastest way to see Space Router in action. A single script starts all 3 components, creates an API key, routes real HTTP and HTTPS traffic through the full proxy chain, and verifies every component.

```bash
bash scripts/e2e-demo.sh
```

The script will:

1. Create virtual environments and install dependencies for each component
2. Start the Coordination API, Home Node, and Proxy Gateway
3. Create an API key and register the Home Node
4. Run 6 test categories (8 assertions) covering HTTP proxying, HTTPS CONNECT tunneling, health checks, metrics, node registration, and API key management
5. Print a summary with pass/fail results
6. Clean up all processes on exit

Expected output on success:

```
═══ Test Summary ═══

  Total:  8
  Passed: 8
  Failed: 0

  *** ALL TESTS PASSED ***

  Architecture verified:
    Agent -> Proxy Gateway (:8080)
         -> Coordination API (:8000) [auth + routing]
         -> Home Node (:9090) [TLS proxy]
         -> Target (httpbin.org)
```

Prerequisites: Python 3.12+, pip, curl, nc (netcat).

## Staging E2E Demo (Fly.io + Residential IP)

Tests the full proxy chain across real infrastructure — Coordination API and Proxy Gateway on Fly.io, Home Node running locally with UPnP port forwarding through a residential router.

```bash
./scripts/e2e-staging-demo.sh
```

Unlike the local demo (which runs everything on localhost with SQLite), the staging demo verifies the production network path:

```
Client (this machine)
  └─ TLS ─→ Proxy Gateway (Fly.io, shared IPv4 + SNI routing)
              ├─→ Coordination API (Fly.io) — auth + node selection
              └─ TLS ─→ Home Node (local, UPnP port-forwarded)
                          └─→ Target (httpbin.org, api.ipify.org)
```

### Prerequisites

- Coordination API deployed at `spacerouter-coordination-api.fly.dev`
- Proxy Gateway deployed at `spacerouter-proxy-gateway.fly.dev:8080`
- Home Node virtualenv installed (`home-node/.venv`)
- UPnP-capable router on the local network
- No VPN active (e.g., Cloudflare WARP — interferes with UPnP gateway detection)

### What it tests

The script runs **15 tests** across 6 groups:

| Group | Tests | What's verified |
|---|---|---|
| **A. Infrastructure Health** | 3 | Coordination API `/healthz`, `/readyz`, node registration |
| **B. Authentication** | 2 | No credentials → 407, bad credentials → 407 |
| **C. HTTP Forward Proxy** | 3 | HTTP proxy returns 200, `X-SpaceRouter-Node` header, `X-SpaceRouter-Request-Id` header |
| **D. HTTPS CONNECT Tunnel** | 3 | HTTPS via httpbin.org, HTTPS via api.ipify.org, exit IP consistency |
| **E. Security** | 2 | No `Proxy-Authorization` leakage to target, residential IP verification |
| **F. Multi-Request** | 2 | 5 sequential requests without rate limiting, API key visible in listing |

### Configuration

| Variable | Default | Description |
|---|---|---|
| `COORD_API_URL` | `https://spacerouter-coordination-api.fly.dev` | Coordination API URL |
| `PROXY_GATEWAY_HOST` | `spacerouter-proxy-gateway.fly.dev` | Proxy Gateway hostname |
| `PROXY_GATEWAY_PORT` | `8080` | Proxy Gateway port |
| `HOME_NODE_DIR` | Auto-detected from script location | Path to `home-node/` directory |

### Cleanup

The script automatically cleans up on exit (including Ctrl+C):
- Stops the Home Node process
- Deregisters the node from the Coordination API
- Removes UPnP port mapping from the router
- Deletes the test API key

### Key differences from local demo

| Aspect | Local (`e2e-demo.sh`) | Staging (`e2e-staging-demo.sh`) |
|---|---|---|
| Coordination API | localhost:8000 (SQLite) | Fly.io (cloud) |
| Proxy Gateway | localhost:8080 | Fly.io shared IPv4 + TLS SNI |
| Home Node | localhost:9090 (loopback) | Real UPnP, residential IP |
| Proxy scheme | `http://` | `https://` + `--proxy-insecure` |
| Network path | All loopback | Internet: Client → Fly.io → Router → Home Node → Target |
| Exit IP | `127.0.0.1` | Residential ISP address |
