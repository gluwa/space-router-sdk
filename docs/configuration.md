# Configuration

All settings are via environment variables with the `SR_` prefix.

## Proxy Gateway

| Variable | Default | Description |
|---|---|---|
| `SR_PROXY_PORT` | 8080 | Port for the proxy server |
| `SR_MANAGEMENT_PORT` | 8081 | Port for health/metrics API |
| `SR_COORDINATION_API_URL` | — | Coordination API base URL |
| `SR_COORDINATION_API_SECRET` | — | Shared secret for internal API auth |
| `SR_SUPABASE_URL` | — | Supabase project URL for request logging |
| `SR_SUPABASE_SERVICE_KEY` | — | Supabase service role key |
| `SR_DEFAULT_RATE_LIMIT_RPM` | 60 | Default requests per minute per API key |
| `SR_NODE_REQUEST_TIMEOUT` | 30.0 | Timeout (seconds) for node requests |
| `SR_AUTH_CACHE_TTL` | 300 | Seconds to cache auth validation results |
| `SR_USE_SQLITE` | false | Use SQLite mode instead of Supabase |

## Coordination API

| Variable | Default | Description |
|---|---|---|
| `SR_PORT` | 8000 | API server port |
| `SR_INTERNAL_API_SECRET` | — | Shared secret for internal endpoints |
| `SR_IPINFO_TOKEN` | — | ipinfo.io API token for IP classification (optional — free tier works without) |
| `SR_SUPABASE_URL` | — | Supabase project URL |
| `SR_SUPABASE_SERVICE_KEY` | — | Supabase service role key |
| `SR_PROXYJET_HOST` | — | ProxyJet hostname (e.g. `proxy-jet.io`). **Required** for fallback routing. |
| `SR_PROXYJET_PORT` | 1010 | ProxyJet HTTP proxy port |
| `SR_PROXYJET_USERNAME` | — | ProxyJet auth username |
| `SR_PROXYJET_PASSWORD` | — | ProxyJet auth password |
| `SR_USE_SQLITE` | false | Use SQLite instead of Supabase |
| `SR_SQLITE_DB_PATH` | space_router.db | Path to SQLite database file |

## Home Node Daemon

| Variable | Default | Description |
|---|---|---|
| `SR_NODE_PORT` | 9090 | TCP server port |
| `SR_COORDINATION_API_URL` | http://localhost:8000 | Coordination API base URL |
| `SR_PUBLIC_IP` | (auto-detected) | Public IP address; auto-detected if empty |
| `SR_NODE_TYPE` | residential | Node type for registration |
| `SR_NODE_LABEL` | — | Human-readable label for this node |
| `SR_NODE_REGION` | — | Region identifier (e.g., us-west, eu-central) |
| `SR_BUFFER_SIZE` | 65536 | TCP read buffer size |
| `SR_REQUEST_TIMEOUT` | 30.0 | Timeout (seconds) for connecting to target servers |
| `SR_RELAY_TIMEOUT` | 300.0 | Max duration (seconds) for a CONNECT tunnel relay |
| `SR_UPNP_ENABLED` | true | Enable UPnP/NAT-PMP for automatic port forwarding |
| `SR_UPNP_LEASE_DURATION` | 3600 | UPnP port mapping lease duration in seconds (0 = permanent) |
