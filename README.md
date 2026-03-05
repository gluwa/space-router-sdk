# Space Router

Residential IP as a Service for AI Agents.

Space Router provides a single proxy URL that routes agent HTTP traffic through residential IP addresses. No SDK required — configure any HTTP client with the proxy URL and go.

## Architecture

| Component | Language | Description |
|---|---|---|
| **Proxy Gateway** | Python / asyncio | Agent-facing HTTP forward proxy. Authenticates requests, selects a residential node, and tunnels traffic through it. |
| **Coordination API** | Python / FastAPI | Central brain. Node registry, IP classification via ipinfo.io, routing decisions, health monitoring, API key management. |
| **Home Node Daemon** | Python / asyncio | Runs on residential machines (macOS). Accepts proxied requests and forwards them from its residential IP. Receives IP classification from the Coordination API at registration. |

```
                     ┌──────────────────┐
   AI Agent ────────►│  Proxy Gateway   │
  (HTTP proxy)       │  :8080 (proxy)   │
                     │  :8081 (mgmt)    │
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │ Coordination API │
                     │  :8000           │
                     │  (Database)      │
                     └────────┬─────────┘
                              │  UPnP / Direct IP
                 ┌────────────┼────────────┐
                 ▼            ▼            ▼
           Home Node    Home Node    proxyjet.io
           :9090        :9090        (fallback)
       (residential)  (residential)
```

Home Nodes run on residential machines behind NAT. UPnP/NAT-PMP automatically configures port forwarding on the router so the Proxy Gateway can reach them without manual setup.

## Database Options

Space Router supports two database options:

1. **Supabase (Default/Production)** - Cloud-based PostgreSQL database with PostgREST API
2. **SQLite (Development)** - Local file-based database for easy development and testing

The SQLite option is perfect for development, testing, and deployments where an external database dependency is not desirable.

## Quick Start (Local Development with SQLite)

### Prerequisites

- Python 3.12+
- pip

### 1. Coordination API with SQLite

```bash
cd coordination-api
pip install -r requirements.txt

# Set environment variables for SQLite mode
export SR_USE_SQLITE=true
export SR_SQLITE_DB_PATH=space_router.db
export SR_INTERNAL_API_SECRET=local-dev-secret

# Optional: ipinfo.io token for IP classification (works without, but rate-limited)
export SR_IPINFO_TOKEN=your-ipinfo-token

# ProxyJet fallback (used when no residential nodes are available)
export SR_PROXYJET_HOST=proxy-jet.io
export SR_PROXYJET_PORT=1010
export SR_PROXYJET_USERNAME=your-proxyjet-username
export SR_PROXYJET_PASSWORD=your-proxyjet-password

# Start the server
python -m app.main
```

### 2. Proxy Gateway

```bash
cd proxy-gateway
pip install -r requirements.txt

# Set required environment variables
export SR_COORDINATION_API_URL=http://localhost:8000
export SR_COORDINATION_API_SECRET=local-dev-secret

# Start the server (proxy on :8080, management API on :8081)
python -m app.main
```

### 3. Home Node Daemon

```bash
cd home-node
pip install -r requirements.txt

# Set required environment variables
export SR_COORDINATION_API_URL=http://localhost:8000

# For local dev, set PUBLIC_IP so it doesn't try external IP detection
export SR_PUBLIC_IP=127.0.0.1

# UPnP: disabled for local dev (no NAT to traverse)
export SR_UPNP_ENABLED=false

# Optional: set node metadata
export SR_NODE_LABEL=my-macbook
export SR_NODE_REGION=us-west

# Start the daemon (listens on :9090)
python -m app.main
```

### 4. Create an API Key

```bash
curl -X POST http://localhost:8000/api-keys \
  -H "Content-Type: application/json" \
  -d '{"name": "My Agent"}'
```

Save the `api_key` from the response — it's only shown once.

### 5. Test End-to-End

```bash
# Send a request through the full pipeline:
# Agent → Proxy Gateway → Home Node → target
curl -x http://sr_live_YOUR_API_KEY@localhost:8080 http://httpbin.org/ip

# Request a specific IP type and region:
curl -x http://sr_live_YOUR_API_KEY@localhost:8080 \
  -H "X-SpaceRouter-IP-Type: residential" \
  -H "X-SpaceRouter-Region: Seoul, KR" \
  http://httpbin.org/ip
```

## Usage in Code

Agents configure their HTTP client with the Space Router proxy URL:

```python
import httpx

proxy_url = "http://sr_live_YOUR_API_KEY@localhost:8080"

async with httpx.AsyncClient(proxy=proxy_url) as client:
    response = await client.get("https://target-website.com/data")
    print(response.status_code)
```

Or with curl:

```bash
curl -x http://sr_live_YOUR_API_KEY@localhost:8080 https://example.com
```

### IP-Based Routing

Agents can request a specific IP type and region by adding headers to their proxy requests:

```python
import httpx

proxy_url = "http://sr_live_YOUR_API_KEY@localhost:8080"

async with httpx.AsyncClient(proxy=proxy_url) as client:
    response = await client.get(
        "https://target-website.com/data",
        headers={
            "X-SpaceRouter-IP-Type": "residential",   # residential, mobile, datacenter, business
            "X-SpaceRouter-Region": "Seoul, KR",       # city, country substring match
        },
    )
```

When a Home Node registers, the Coordination API calls [ipinfo.io](https://ipinfo.io) to classify its public IP:

- **IP type:** residential, mobile, datacenter, or business (derived from ipinfo privacy/company/carrier/org data)
- **Region:** city and country code (e.g., "Seoul, KR", "Ashburn, US")

The routing headers are stripped before the request is forwarded to the Home Node. If no node matches the requested type/region, the router falls back to any available node.

## Running Tests

```bash
# Coordination API (47 tests)
cd coordination-api && pytest tests/ -v

# Proxy Gateway (36 tests)
cd proxy-gateway && pytest tests/ -v

# Home Node Daemon (36 tests)
cd home-node && pytest tests/ -v
```

## Documentation

| Document | Description |
|---|---|
| [API Reference](docs/API.md) | Full API documentation for all endpoints |
| [Configuration](docs/configuration.md) | All environment variables for each component |
| [Deployment](docs/deployment.md) | Production deployment (Fly.io, macOS launchd, Docker, Supabase) and ProxyJet fallback |
| [E2E Testing](docs/e2e-testing.md) | Local and staging end-to-end demo scripts |
| [UPnP / NAT-PMP](docs/upnp.md) | Automatic port forwarding setup for Home Nodes |
