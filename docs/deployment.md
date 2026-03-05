# Production Deployment

## Coordination API (Fly.io)

```bash
cd coordination-api

# For Supabase deployment
fly secrets set \
  SR_USE_SQLITE=false \
  SR_SUPABASE_URL=https://your-project.supabase.co \
  SR_SUPABASE_SERVICE_KEY=your-service-key \
  SR_INTERNAL_API_SECRET=your-strong-secret \
  SR_IPINFO_TOKEN=your-ipinfo-token \
  SR_PROXYJET_HOST=proxy-jet.io \
  SR_PROXYJET_PORT=1010 \
  SR_PROXYJET_USERNAME=your-proxyjet-username \
  SR_PROXYJET_PASSWORD=your-proxyjet-password

# OR for SQLite deployment
# fly secrets set \
#   SR_USE_SQLITE=true \
#   SR_SQLITE_DB_PATH=/data/space_router.db \
#   SR_INTERNAL_API_SECRET=your-strong-secret \
#   SR_PROXYJET_HOST=proxy-jet.io \
#   SR_PROXYJET_PORT=1010 \
#   SR_PROXYJET_USERNAME=your-proxyjet-username \
#   SR_PROXYJET_PASSWORD=your-proxyjet-password

fly deploy
```

## Proxy Gateway (Fly.io)

```bash
cd proxy-gateway

fly secrets set \
  SR_COORDINATION_API_URL=https://coordination.spacerouter.io \
  SR_COORDINATION_API_SECRET=your-strong-secret

fly deploy
```

## Home Node Daemon (macOS)

The Home Node runs on residential machines. For production on macOS:

**Option A: Run directly**

```bash
cd home-node
pip install -r requirements.txt

export SR_COORDINATION_API_URL=https://coordination.spacerouter.io
export SR_NODE_LABEL=macbook-home
export SR_NODE_REGION=us-west

python -m app.main
```

**Option B: Install as a macOS launchd service (auto-start on boot)**

```bash
# 1. Install the code
sudo mkdir -p /opt/spacerouter/home-node
sudo cp -r home-node/* /opt/spacerouter/home-node/
cd /opt/spacerouter/home-node && pip install -r requirements.txt

# 2. Edit the plist to set your Coordination API URL and node metadata
vim home-node/launchd/com.spacerouter.homenode.plist

# 3. Install and start the service
cp home-node/launchd/com.spacerouter.homenode.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spacerouter.homenode.plist

# Check status
launchctl list | grep spacerouter

# View logs
tail -f /tmp/spacerouter-homenode.stdout.log
tail -f /tmp/spacerouter-homenode.stderr.log

# Stop the service
launchctl unload ~/Library/LaunchAgents/com.spacerouter.homenode.plist
```

**Option C: Docker**

```bash
cd home-node
docker build -t spacerouter-homenode .
docker run -d \
  -p 9090:9090 \
  -e SR_COORDINATION_API_URL=https://coordination.spacerouter.io \
  -e SR_NODE_LABEL=docker-node \
  -e SR_NODE_REGION=us-west \
  spacerouter-homenode
```

## Quick Start (Production with Supabase)

### 1. Database Setup

Run `coordination-api/schema.sql` in the Supabase SQL Editor to create the required tables (`api_keys`, `nodes`, `route_outcomes`, `request_logs`).

### 2. Coordination API

```bash
cd coordination-api
pip install -r requirements.txt

# Set required environment variables
export SR_USE_SQLITE=false  # Explicitly disable SQLite
export SR_SUPABASE_URL=https://your-project.supabase.co
export SR_SUPABASE_SERVICE_KEY=your-service-key
export SR_INTERNAL_API_SECRET=shared-secret

# ProxyJet fallback (used when no residential nodes are available)
export SR_PROXYJET_HOST=proxy-jet.io
export SR_PROXYJET_PORT=1010
export SR_PROXYJET_USERNAME=your-proxyjet-username
export SR_PROXYJET_PASSWORD=your-proxyjet-password

# Start the server
python -m app.main
```

Follow the remaining steps from the [Quick Start (Local Development)](../README.md#quick-start-local-development-with-sqlite) section for setting up the Proxy Gateway and Home Node.

## ProxyJet Fallback

When no residential home nodes are online, the Coordination API automatically falls back to [ProxyJet](https://proxy-jet.io) rotating-residential proxies. This ensures requests never fail with a 503 as long as ProxyJet credentials are configured.

**Routing priority:**
1. Online residential home nodes (weighted by health score)
2. ProxyJet rotating-residential fallback
3. 503 Service Unavailable (only if ProxyJet is not configured)

The four `SR_PROXYJET_*` environment variables are required on the Coordination API for fallback to work. They are already set as Fly.io secrets on `spacerouter-coordination-api`. For local development, copy `.env.example` to `.env` inside `coordination-api/` and fill in your credentials.
