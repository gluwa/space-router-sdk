"""End-to-end tests for ProxyJet fallback routing.

Each test spins up:
  1. A fake "ProxyJet" upstream proxy (TCP server that validates Proxy-Authorization)
  2. The Space Router proxy gateway wired to return the fake ProxyJet as the selected node

Then sends real client traffic through the full pipeline:
  Client → Proxy Gateway → fake ProxyJet → (response)
"""

import asyncio
import base64

import pytest

from app.auth import AuthResult
from app.config import Settings
from app.proxy import ProxyServer, parse_headers
from app.rate_limiter import RateLimiter
from app.routing import NodeSelection


# ---------------------------------------------------------------------------
# Fake collaborators (same pattern as test_proxy.py)
# ---------------------------------------------------------------------------

class FakeAuthValidator:
    _DEFAULT = AuthResult(valid=True, api_key_id="test-key-id", rate_limit_rpm=60)

    def __init__(self, result: AuthResult | None = _DEFAULT):
        self._result = result

    async def validate(self, api_key: str) -> AuthResult | None:
        return self._result


class FakeRequestLogger:
    def __init__(self):
        self.logs = []

    def log(self, entry):
        self.logs.append(entry)


class FakeNodeRouter:
    """Returns a fixed node whose endpoint_url contains ProxyJet-style credentials."""

    def __init__(self, node: NodeSelection | None = None):
        self._node = node
        self.reports: list[dict] = []

    async def select_node(self, *, region=None, node_type=None) -> NodeSelection | None:
        return self._node

    def report_outcome(self, node_id, success, latency_ms, bytes_transferred):
        self.reports.append({
            "node_id": node_id,
            "success": success,
            "latency_ms": latency_ms,
            "bytes": bytes_transferred,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROXYJET_USER = "260302CJd90-resi-US"
PROXYJET_PASS = "NwUqzgu38XCisgJ"
EXPECTED_PROXY_AUTH = "Basic " + base64.b64encode(
    f"{PROXYJET_USER}:{PROXYJET_PASS}".encode()
).decode()


def _client_creds() -> str:
    """Proxy-Authorization value a Space Router client would send."""
    return base64.b64encode(b"sr_live_testkey123:").decode()


# ---------------------------------------------------------------------------
# Tests — HTTP forward through ProxyJet
# ---------------------------------------------------------------------------

class TestProxyJetHTTPForward:
    @pytest.mark.asyncio
    async def test_http_forward_passes_proxy_auth_to_upstream(self):
        """Full pipeline: client → gateway → fake ProxyJet.

        Verifies that the gateway:
        - Strips the client's Proxy-Authorization
        - Adds ProxyJet's Proxy-Authorization (from the endpoint URL creds)
        - Forwards the request and relays the response back
        """
        received_requests: list[bytes] = []

        async def fake_proxyjet_handler(reader, writer):
            # Read forwarded HTTP request
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            received_requests.append(data)

            # Send a simple HTTP response
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 27\r\n"
                b"\r\n"
                b'{"ip":"203.0.113.42","ok":1}'
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        fake_proxyjet = await asyncio.start_server(fake_proxyjet_handler, "127.0.0.1", 0)
        pj_port = fake_proxyjet.sockets[0].getsockname()[1]

        # Build endpoint URL with ProxyJet credentials (same format as RoutingService)
        endpoint_url = f"http://{PROXYJET_USER}:{PROXYJET_PASS}@127.0.0.1:{pj_port}"

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )
        fake_logger = FakeRequestLogger()
        fake_router = FakeNodeRouter(
            node=NodeSelection(node_id="proxyjet-fallback", endpoint_url=endpoint_url)
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=fake_router,
            rate_limiter=RateLimiter(),
            request_logger=fake_logger,
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = _client_creds()
            writer.write(
                f"GET http://httpbin.org/ip HTTP/1.1\r\n"
                f"Host: httpbin.org\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            response_str = response.decode("latin-1")

            # Verify response came back through the pipeline
            assert "200 OK" in response_str
            assert "203.0.113.42" in response_str
            assert "X-SpaceRouter-Node: proxyjet-fallback" in response_str
            assert "X-SpaceRouter-Request-Id:" in response_str

            writer.close()
            await writer.wait_closed()

            # Verify what the fake ProxyJet received
            assert len(received_requests) == 1
            req_str = received_requests[0].decode("latin-1")

            # Gateway must have added ProxyJet's Proxy-Authorization
            assert f"Proxy-Authorization: {EXPECTED_PROXY_AUTH}" in req_str

            # Gateway must have stripped the client's original Proxy-Authorization
            assert f"Basic {creds}" not in req_str

            # The original request target must be preserved
            assert "GET http://httpbin.org/ip" in req_str

            # Verify logging recorded the request
            await asyncio.sleep(0.1)
            assert len(fake_logger.logs) == 1
            assert fake_logger.logs[0].success is True
            assert fake_logger.logs[0].node_id == "proxyjet-fallback"

            # Verify outcome was reported
            assert len(fake_router.reports) == 1
            assert fake_router.reports[0]["node_id"] == "proxyjet-fallback"
            assert fake_router.reports[0]["success"] is True

        finally:
            server.close()
            await server.wait_closed()
            fake_proxyjet.close()
            await fake_proxyjet.wait_closed()


# ---------------------------------------------------------------------------
# Tests — CONNECT tunnel through ProxyJet
# ---------------------------------------------------------------------------

class TestProxyJetCONNECT:
    @pytest.mark.asyncio
    async def test_connect_tunnel_passes_proxy_auth_to_upstream(self):
        """Full pipeline for CONNECT: client → gateway → fake ProxyJet → tunnel.

        Verifies that the gateway:
        - Sends CONNECT with ProxyJet's Proxy-Authorization to the upstream
        - Relays the 200 Connection Established back to the client
        - Tunnels raw bytes bidirectionally
        """
        received_connect_requests: list[bytes] = []

        async def fake_proxyjet_handler(reader, writer):
            # Read the CONNECT request
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk

            received_connect_requests.append(data)

            # Respond with 200 Connection Established
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            # Echo back whatever comes through the tunnel
            try:
                while True:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=2.0)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
            except (asyncio.TimeoutError, ConnectionResetError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        fake_proxyjet = await asyncio.start_server(fake_proxyjet_handler, "127.0.0.1", 0)
        pj_port = fake_proxyjet.sockets[0].getsockname()[1]

        endpoint_url = f"http://{PROXYJET_USER}:{PROXYJET_PASS}@127.0.0.1:{pj_port}"

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )
        fake_router = FakeNodeRouter(
            node=NodeSelection(node_id="proxyjet-fallback", endpoint_url=endpoint_url)
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=fake_router,
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = _client_creds()
            writer.write(
                f"CONNECT example.com:443 HTTP/1.1\r\n"
                f"Host: example.com:443\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            # Read the 200 Connection Established from the gateway
            response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            response_str = response.decode("latin-1")
            assert "200 Connection Established" in response_str
            assert "X-SpaceRouter-Node: proxyjet-fallback" in response_str

            # Send data through the tunnel and verify echo
            writer.write(b"TLS CLIENT HELLO (simulated)")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert echoed == b"TLS CLIENT HELLO (simulated)"

            writer.close()
            await writer.wait_closed()

            # Verify what the fake ProxyJet received
            assert len(received_connect_requests) == 1
            connect_str = received_connect_requests[0].decode("latin-1")

            # Must contain CONNECT target
            assert "CONNECT example.com:443" in connect_str

            # Must have ProxyJet's auth header
            assert f"Proxy-Authorization: {EXPECTED_PROXY_AUTH}" in connect_str

        finally:
            server.close()
            await server.wait_closed()
            fake_proxyjet.close()
            await fake_proxyjet.wait_closed()

    @pytest.mark.asyncio
    async def test_connect_fails_when_upstream_rejects_auth(self):
        """If the upstream proxy rejects auth, the gateway returns 502."""

        async def fake_proxyjet_rejecting(reader, writer):
            # Read the CONNECT request
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk

            # Reject with 407
            writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        fake_proxyjet = await asyncio.start_server(fake_proxyjet_rejecting, "127.0.0.1", 0)
        pj_port = fake_proxyjet.sockets[0].getsockname()[1]

        endpoint_url = f"http://bad_user:bad_pass@127.0.0.1:{pj_port}"

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="proxyjet-fallback", endpoint_url=endpoint_url)
            ),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = _client_creds()
            writer.write(
                f"CONNECT example.com:443 HTTP/1.1\r\n"
                f"Host: example.com:443\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            # Gateway should return 502 upstream error
            assert b"502" in response

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            fake_proxyjet.close()
            await fake_proxyjet.wait_closed()


# ---------------------------------------------------------------------------
# Tests — ProxyJet fallback node selection integration
# ---------------------------------------------------------------------------

class TestProxyJetNodeSelection:
    @pytest.mark.asyncio
    async def test_no_node_returns_503(self):
        """When NodeRouter returns None (no nodes, no ProxyJet), client gets 503."""
        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(node=None),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = _client_creds()
            writer.write(
                f"GET http://example.com/ HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"503" in response
            assert b"no_nodes_available" in response

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_proxyjet_fallback_node_id_in_response_headers(self):
        """X-SpaceRouter-Node should show 'proxyjet-fallback' when fallback is used."""
        async def fake_handler(reader, writer):
            # Read full request headers (until blank line)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 2\r\n"
                b"\r\n"
                b"OK"
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        fake_server = await asyncio.start_server(fake_handler, "127.0.0.1", 0)
        port = fake_server.sockets[0].getsockname()[1]

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(
                node=NodeSelection(
                    node_id="proxyjet-fallback",
                    endpoint_url=f"http://127.0.0.1:{port}",
                )
            ),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = _client_creds()
            writer.write(
                f"GET http://example.com/ HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            # Read until we get the full response (headers + body)
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                response += chunk
            # Read body after headers
            if b"\r\n\r\n" in response:
                remaining = await asyncio.wait_for(reader.read(4096), timeout=2.0)
                response += remaining
            response_str = response.decode("latin-1")

            assert "200 OK" in response_str
            assert "X-SpaceRouter-Node: proxyjet-fallback" in response_str

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            fake_server.close()
            await fake_server.wait_closed()
