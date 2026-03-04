#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Space Router — Local End-to-End Demo
#
# Starts all 3 components, creates an API key, routes HTTP and HTTPS
# requests through the full proxy chain, and verifies every component.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_DIR="$REPO_ROOT/coordination-api"
GATEWAY_DIR="$REPO_ROOT/proxy-gateway"
HOME_NODE_DIR="$REPO_ROOT/home-node"

COORD_PORT=8000
GATEWAY_PROXY_PORT=8080
GATEWAY_MGMT_PORT=8081
HOME_NODE_PORT=9090

COORD_PID=""
GATEWAY_PID=""
HOME_NODE_PID=""

PASS=0
FAIL=0
TOTAL=0

# ─── Cleanup trap ─────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "═══ Cleaning up ═══"
    for pid_var in GATEWAY_PID HOME_NODE_PID COORD_PID; do
        pid="${!pid_var}"
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping PID $pid ($pid_var)..."
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    echo "  Done."
}
trap cleanup EXIT INT TERM

# ─── Helpers ──────────────────────────────────────────────────────────
log()    { echo "  [$1] $2"; }
pass()   { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); log "PASS" "$1"; }
fail()   { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); log "FAIL" "$1"; }
header() { echo ""; echo "═══ $1 ═══"; }

wait_for_http() {
    local url="$1" max_wait="${2:-15}" interval="${3:-1}"
    local elapsed=0
    while (( elapsed < max_wait )); do
        if curl -sf "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done
    return 1
}

wait_for_tcp() {
    local host="$1" port="$2" max_wait="${3:-15}"
    local elapsed=0
    while (( elapsed < max_wait )); do
        if nc -z "$host" "$port" 2>/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ─── Setup ────────────────────────────────────────────────────────────
header "Setting up virtual environments"

for component_dir in "$COORD_DIR" "$GATEWAY_DIR" "$HOME_NODE_DIR"; do
    name="$(basename "$component_dir")"
    venv_dir="$component_dir/.venv"
    if [[ ! -d "$venv_dir" ]]; then
        echo "  Creating venv for $name..."
        python3 -m venv "$venv_dir"
    fi
    echo "  Installing deps for $name..."
    "$venv_dir/bin/pip" install -q -r "$component_dir/requirements.txt" 2>&1 | tail -1
done

# ─── Clean stale state ────────────────────────────────────────────────
header "Cleaning stale state"
rm -f "$COORD_DIR/space_router.db"
rm -rf "$HOME_NODE_DIR/certs"
mkdir -p "$REPO_ROOT/logs"
echo "  Removed stale database, certificates; created logs dir"

# ─── Write .env files ─────────────────────────────────────────────────
header "Configuring environment"

cat > "$COORD_DIR/.env" << 'EOF'
SR_USE_SQLITE=true
SR_SQLITE_DB_PATH=space_router.db
SR_INTERNAL_API_SECRET=
SR_LOG_LEVEL=INFO
EOF

cat > "$GATEWAY_DIR/.env" << 'EOF'
SR_COORDINATION_API_URL=http://localhost:8000
SR_COORDINATION_API_SECRET=test_secret
SR_USE_SQLITE=true
SR_LOG_LEVEL=INFO
EOF

cat > "$HOME_NODE_DIR/.env" << 'EOF'
SR_COORDINATION_API_URL=http://localhost:8000
SR_PUBLIC_IP=127.0.0.1
SR_UPNP_ENABLED=false
SR_NODE_LABEL=local-demo
SR_NODE_REGION=local
SR_LOG_LEVEL=INFO
EOF

echo "  Environment files written"

# ═══════════════════════════════════════════════════════════════════════
# Start services
# ═══════════════════════════════════════════════════════════════════════

# ─── 1. Coordination API ──────────────────────────────────────────────
header "Starting Coordination API (port $COORD_PORT)"
cd "$COORD_DIR"
"$COORD_DIR/.venv/bin/uvicorn" app.main:app \
    --host 127.0.0.1 --port "$COORD_PORT" \
    --log-level info \
    > "$REPO_ROOT/logs/coord-api.log" 2>&1 &
COORD_PID=$!
cd "$REPO_ROOT"

if ! wait_for_http "http://localhost:$COORD_PORT/healthz" 15; then
    echo "  ERROR: Coordination API failed to start. Logs:"
    cat "$REPO_ROOT/logs/coord-api.log"
    exit 1
fi
echo "  Coordination API running (PID $COORD_PID)"

# ─── 2. Create API key ────────────────────────────────────────────────
header "Creating API key"
API_KEY_RESPONSE=$(curl -sf -X POST "http://localhost:$COORD_PORT/api-keys" \
    -H "Content-Type: application/json" \
    -d '{"name": "e2e-demo-agent", "rate_limit_rpm": 60}')
API_KEY=$(echo "$API_KEY_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
API_KEY_ID=$(echo "$API_KEY_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "  API key created: ${API_KEY:0:20}..."
echo "  Key ID: $API_KEY_ID"

# ─── 3. Home Node ─────────────────────────────────────────────────────
header "Starting Home Node (port $HOME_NODE_PORT)"
cd "$HOME_NODE_DIR"
"$HOME_NODE_DIR/.venv/bin/python" -m app.main \
    > "$REPO_ROOT/logs/home-node.log" 2>&1 &
HOME_NODE_PID=$!
cd "$REPO_ROOT"

if ! wait_for_tcp 127.0.0.1 "$HOME_NODE_PORT" 20; then
    echo "  ERROR: Home Node failed to start. Logs:"
    cat "$REPO_ROOT/logs/home-node.log"
    exit 1
fi

# Verify registration
sleep 2
NODE_COUNT=$(curl -sf "http://localhost:$COORD_PORT/nodes" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [[ "$NODE_COUNT" -ge 1 ]]; then
    echo "  Home Node running and registered (PID $HOME_NODE_PID, $NODE_COUNT node(s))"
else
    echo "  WARNING: Home Node running but registration not confirmed"
    cat "$REPO_ROOT/logs/home-node.log"
fi

# ─── 4. Proxy Gateway ─────────────────────────────────────────────────
header "Starting Proxy Gateway (proxy:$GATEWAY_PROXY_PORT mgmt:$GATEWAY_MGMT_PORT)"
cd "$GATEWAY_DIR"
"$GATEWAY_DIR/.venv/bin/python" -m app.main \
    > "$REPO_ROOT/logs/gateway.log" 2>&1 &
GATEWAY_PID=$!
cd "$REPO_ROOT"

if ! wait_for_http "http://localhost:$GATEWAY_MGMT_PORT/healthz" 15; then
    echo "  ERROR: Proxy Gateway failed to start. Logs:"
    cat "$REPO_ROOT/logs/gateway.log"
    exit 1
fi
echo "  Proxy Gateway running (PID $GATEWAY_PID)"

# ═══════════════════════════════════════════════════════════════════════
# Run E2E Tests
# ═══════════════════════════════════════════════════════════════════════
header "Running E2E Tests"

# ── Test 1: HTTP forward proxy ────────────────────────────────────────
echo ""
echo "── Test 1: HTTP forward proxy via Home Node ──"
HTTP_RESPONSE=$(curl -s --max-time 30 -D - \
    -x "http://${API_KEY}:@localhost:$GATEWAY_PROXY_PORT" \
    "http://httpbin.org/ip" 2>&1) || true

HTTP_STATUS=$(echo "$HTTP_RESPONSE" | grep "^HTTP/" | head -1 | awk '{print $2}')
SR_NODE=$(echo "$HTTP_RESPONSE" | grep -i "X-SpaceRouter-Node" | tr -d '\r' || true)
SR_REQ_ID=$(echo "$HTTP_RESPONSE" | grep -i "X-SpaceRouter-Request-Id" | tr -d '\r' || true)
HTTP_BODY=$(echo "$HTTP_RESPONSE" | tail -1)

if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "HTTP forward proxy returned 200"
else
    fail "HTTP forward proxy returned '$HTTP_STATUS' (expected 200)"
fi
if [[ -n "$SR_NODE" ]]; then
    pass "X-SpaceRouter-Node header present"
    echo "    $SR_NODE"
else
    fail "X-SpaceRouter-Node header missing"
fi
if [[ -n "$SR_REQ_ID" ]]; then
    pass "X-SpaceRouter-Request-Id header present"
    echo "    $SR_REQ_ID"
else
    fail "X-SpaceRouter-Request-Id header missing"
fi
echo "  Response body: $HTTP_BODY"

# ── Test 2: HTTPS CONNECT proxy ──────────────────────────────────────
echo ""
echo "── Test 2: HTTPS CONNECT proxy via Home Node ──"
HTTPS_BODY=$(curl -s --max-time 30 \
    -x "http://${API_KEY}:@localhost:$GATEWAY_PROXY_PORT" \
    --proxy-insecure \
    "https://httpbin.org/ip" 2>&1) || true

# Check if we got a valid JSON response with "origin"
if echo "$HTTPS_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'origin' in d" 2>/dev/null; then
    pass "HTTPS CONNECT proxy returned valid response"
    echo "  Response body: $HTTPS_BODY"
else
    fail "HTTPS CONNECT proxy failed: $HTTPS_BODY"
fi

# ── Test 3: Gateway health ────────────────────────────────────────────
echo ""
echo "── Test 3: Gateway management health ──"
HEALTH_RESPONSE=$(curl -sf "http://localhost:$GATEWAY_MGMT_PORT/healthz" 2>&1) || true

if echo "$HEALTH_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='healthy'" 2>/dev/null; then
    pass "Management /healthz returned healthy"
else
    fail "Management /healthz unexpected: $HEALTH_RESPONSE"
fi

# ── Test 4: Gateway metrics ───────────────────────────────────────────
echo ""
echo "── Test 4: Gateway metrics ──"
METRICS_RESPONSE=$(curl -sf "http://localhost:$GATEWAY_MGMT_PORT/metrics" 2>&1) || true
TOTAL_REQUESTS=$(echo "$METRICS_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_requests',0))" 2>/dev/null) || TOTAL_REQUESTS=0

if [[ "$TOTAL_REQUESTS" -ge 2 ]]; then
    pass "Metrics show $TOTAL_REQUESTS total requests (expected >= 2)"
else
    fail "Metrics show $TOTAL_REQUESTS total requests (expected >= 2)"
fi
echo "  Full metrics: $METRICS_RESPONSE"

# ── Test 5: List nodes ────────────────────────────────────────────────
echo ""
echo "── Test 5: Registered nodes ──"
NODES_RESPONSE=$(curl -sf "http://localhost:$COORD_PORT/nodes" 2>&1) || true
NODE_COUNT=$(echo "$NODES_RESPONSE" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null) || NODE_COUNT=0

if [[ "$NODE_COUNT" -ge 1 ]]; then
    pass "Found $NODE_COUNT registered node(s)"
else
    fail "No nodes found (expected >= 1)"
fi
echo "$NODES_RESPONSE" | python3 -c "
import sys, json
for n in json.load(sys.stdin):
    print(f\"  Node {n['id'][:8]}... status={n['status']} health={n.get('health_score','?')} endpoint={n['endpoint_url']}\")
" 2>/dev/null || true

# ── Test 6: List API keys ─────────────────────────────────────────────
echo ""
echo "── Test 6: API keys ──"
KEYS_RESPONSE=$(curl -sf "http://localhost:$COORD_PORT/api-keys" 2>&1) || true
KEY_COUNT=$(echo "$KEYS_RESPONSE" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null) || KEY_COUNT=0

if [[ "$KEY_COUNT" -ge 1 ]]; then
    pass "Found $KEY_COUNT API key(s)"
else
    fail "No API keys found (expected >= 1)"
fi
echo "$KEYS_RESPONSE" | python3 -c "
import sys, json
for k in json.load(sys.stdin):
    print(f\"  Key {k['id'][:8]}... name={k['name']} prefix={k['key_prefix']} active={k['is_active']}\")
" 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════
header "Test Summary"
echo ""
echo "  Total:  $TOTAL"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [[ "$FAIL" -eq 0 ]]; then
    echo "  *** ALL TESTS PASSED ***"
    echo ""
    echo "  Architecture verified:"
    echo "    Agent -> Proxy Gateway (:$GATEWAY_PROXY_PORT)"
    echo "         -> Coordination API (:$COORD_PORT) [auth + routing]"
    echo "         -> Home Node (:$HOME_NODE_PORT) [TLS proxy]"
    echo "         -> Target (httpbin.org)"
    echo ""
    echo "  Services:"
    echo "    Coordination API:  http://localhost:$COORD_PORT"
    echo "    Proxy Gateway:     http://localhost:$GATEWAY_PROXY_PORT"
    echo "    Management API:    http://localhost:$GATEWAY_MGMT_PORT"
    echo "    Home Node:         https://127.0.0.1:$HOME_NODE_PORT (TLS)"
    echo ""
    echo "  Try it yourself:"
    echo "    curl -x \"http://${API_KEY}:@localhost:$GATEWAY_PROXY_PORT\" http://httpbin.org/ip"
    exit 0
else
    echo "  *** $FAIL TEST(S) FAILED ***"
    echo "  Check logs in $REPO_ROOT/logs/ for details"
    exit 1
fi
