# Space Router

Residential IP as a Service for AI Agents.

Space Router provides a single proxy URL that routes agent HTTP traffic through residential IP addresses. No SDK required — configure any HTTP client with the proxy URL and go.

## Architecture

| Component | Language | Description |
|---|---|---|
| **Proxy Gateway** | Python / asyncio | Agent-facing HTTP forward proxy. Authenticates requests, selects a residential node, and tunnels traffic through it. |
| Coordination API | Python / FastAPI | Central brain. Node registry, routing decisions, health monitoring, API key management. |
| Home Node Daemon | Go | Runs on residential machines. Accepts proxied requests and forwards them from its residential IP. |

## Quick Start

### Prerequisites

- Python 3.12+
- pip

### Proxy Gateway

```bash
cd proxy-gateway
pip install -r requirements.txt

# Set required environment variables
export SR_COORDINATION_API_URL=http://localhost:8000
export SR_COORDINATION_API_SECRET=your-secret

# Start the server (proxy on :8080, management API on :8081)
python -m app.main
```

### Usage

Agents configure their HTTP client with the Space Router proxy URL:

```python
import httpx

proxy_url = "http://sr_live_YOUR_API_KEY@proxy.spacerouter.io:8080"

async with httpx.AsyncClient(proxy=proxy_url) as client:
    response = await client.get("https://target-website.com/data")
    print(response.status_code)
```

Or with curl:

```bash
curl -x http://sr_live_YOUR_API_KEY@proxy.spacerouter.io:8080 https://example.com
```

### Running Tests

```bash
cd proxy-gateway
pytest tests/ -v
```

## Configuration

All settings are via environment variables with the `SR_` prefix:

| Variable | Default | Description |
|---|---|---|
| `SR_PROXY_PORT` | 8080 | Port for the proxy server |
| `SR_MANAGEMENT_PORT` | 8081 | Port for health/metrics API |
| `SR_COORDINATION_API_URL` | — | Coordination API base URL |
| `SR_COORDINATION_API_SECRET` | — | Shared secret for internal API auth |
| `SR_SUPABASE_URL` | — | Supabase project URL for request logging |
| `SR_SUPABASE_SERVICE_KEY` | — | Supabase service role key |
| `SR_DEFAULT_RATE_LIMIT_RPM` | 60 | Default requests per minute per API key |
| `SR_NODE_REQUEST_TIMEOUT` | 30.0 | Timeout (seconds) for home node requests |
| `SR_AUTH_CACHE_TTL` | 300 | Seconds to cache auth validation results |

## API

### Proxy (port 8080)

Standard HTTP forward proxy. Agents send requests through it like any other proxy.

**Authentication:** `Proxy-Authorization: Basic base64(api_key:)`

**Response headers:**

| Header | Description |
|---|---|
| `X-SpaceRouter-Node` | ID of the node that served the request |
| `X-SpaceRouter-Latency` | Internal routing latency in ms |
| `X-SpaceRouter-Request-Id` | Unique request ID for debugging |

**Error codes:** 407 (auth required), 429 (rate limited), 502 (upstream error), 503 (no nodes)

### Management (port 8081)

| Endpoint | Description |
|---|---|
| `GET /healthz` | Liveness check |
| `GET /readyz` | Readiness check (pings Coordination API) |
| `GET /metrics` | Request counts and connection stats |
