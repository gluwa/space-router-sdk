import asyncio
import base64

import pytest

from app.auth import AuthValidator, AuthResult
from app.config import Settings
from app.errors import proxy_auth_required
from app.logger import RequestLogger
from app.proxy import ProxyServer, parse_headers, _read_request_head
from app.rate_limiter import RateLimiter
from app.routing import NodeRouter, NodeSelection


class FakeAuthValidator:
    """Fake auth validator that returns a configurable result.

    Pass result=None to simulate auth failure (proxy checks `if not auth_result`).
    Default: valid auth with test key.
    """
    _DEFAULT = AuthResult(valid=True, api_key_id="test-key-id", rate_limit_rpm=60)

    def __init__(self, result: AuthResult | None = _DEFAULT):
        self._result = result

    async def validate(self, api_key: str) -> AuthResult | None:
        return self._result


class FakeNodeRouter:
    def __init__(self, node: NodeSelection | None = None):
        self._node = node
        self.reports: list[dict] = []
        self.last_select_kwargs: dict = {}

    async def select_node(self, *, ip_type=None, ip_region=None) -> NodeSelection | None:
        self.last_select_kwargs = {"ip_type": ip_type, "ip_region": ip_region}
        return self._node

    def report_outcome(self, node_id, success, latency_ms, bytes_transferred):
        self.reports.append({
            "node_id": node_id,
            "success": success,
            "latency_ms": latency_ms,
            "bytes": bytes_transferred,
        })


class FakeRequestLogger:
    def __init__(self):
        self.logs = []

    def log(self, entry):
        self.logs.append(entry)


class TestParseHeaders:
    def test_basic_headers(self):
        raw = b"Host: example.com\r\nContent-Type: text/html\r\n"
        headers = parse_headers(raw)
        assert headers["Host"] == "example.com"
        assert headers["Content-Type"] == "text/html"

    def test_empty(self):
        assert parse_headers(b"") == {}


class TestProxyServerAuth:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_407(self):
        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )
        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            # Send request without auth
            writer.write(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"407" in response
            assert b"proxy_auth_required" in response

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_invalid_auth_returns_407(self):
        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )
        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(None),  # None = auth failed
            node_router=FakeNodeRouter(),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            creds = base64.b64encode(b"bad_key:").decode()
            writer.write(
                f"GET http://example.com/ HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"407" in response
            assert b"proxy_auth_required" in response

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestProxyServerNoNodes:
    @pytest.mark.asyncio
    async def test_no_nodes_returns_503(self):
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
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            creds = base64.b64encode(b"sr_live_abc123:").decode()
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


class TestProxyServerRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self):
        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
            DEFAULT_RATE_LIMIT_RPM=2,
        )
        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(AuthResult(valid=True, api_key_id="key1", rate_limit_rpm=2)),
            node_router=FakeNodeRouter(node=None),  # Will hit 503 after rate check
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        port = server.sockets[0].getsockname()[1]

        try:
            creds = base64.b64encode(b"sr_live_abc123:").decode()

            # First 2 requests pass rate limit (hit 503 because no nodes)
            for _ in range(2):
                r, w = await asyncio.open_connection("127.0.0.1", port)
                w.write(
                    f"GET http://example.com/ HTTP/1.1\r\n"
                    f"Host: example.com\r\n"
                    f"Proxy-Authorization: Basic {creds}\r\n"
                    f"\r\n".encode()
                )
                await w.drain()
                resp = await asyncio.wait_for(r.read(4096), timeout=5.0)
                assert b"503" in resp  # no nodes, but passed rate limit
                w.close()
                await w.wait_closed()

            # 3rd request should be rate limited
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(
                f"GET http://example.com/ HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await w.drain()
            resp = await asyncio.wait_for(r.read(4096), timeout=5.0)
            assert b"429" in resp
            assert b"rate_limited" in resp
            w.close()
            await w.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestProxyServerHTTPForward:
    @pytest.mark.asyncio
    async def test_http_forward_with_mock_node(self):
        """Start a fake home node, then proxy an HTTP request through it."""
        # Start a fake home node that echoes a response
        async def fake_node_handler(reader, writer):
            # Read the forwarded request
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            # Send a simple HTTP response
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 11\r\n"
                b"\r\n"
                b"Hello World"
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        fake_node = await asyncio.start_server(fake_node_handler, "127.0.0.1", 0)
        node_port = fake_node.sockets[0].getsockname()[1]

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        fake_logger = FakeRequestLogger()
        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-1", endpoint_url=f"http://127.0.0.1:{node_port}")
            ),
            rate_limiter=RateLimiter(),
            request_logger=fake_logger,
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = base64.b64encode(b"sr_live_abc123:").decode()
            writer.write(
                f"GET http://example.com/test HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            response_str = response.decode("latin-1")

            assert "200 OK" in response_str
            assert "X-SpaceRouter-Node: node-1" in response_str
            assert "X-SpaceRouter-Request-Id:" in response_str
            assert "Hello World" in response_str

            writer.close()
            await writer.wait_closed()

            # Verify logging
            await asyncio.sleep(0.1)
            assert len(fake_logger.logs) == 1
            assert fake_logger.logs[0].success is True
            assert fake_logger.logs[0].method == "GET"
        finally:
            server.close()
            await server.wait_closed()
            fake_node.close()
            await fake_node.wait_closed()


class TestProxyServerRoutingHeaders:
    @pytest.mark.asyncio
    async def test_routing_headers_forwarded_to_select_node(self):
        """X-SpaceRouter-IP-Type and X-SpaceRouter-Region should be extracted
        and forwarded to select_node as ip_type/ip_region kwargs."""
        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        fake_router = FakeNodeRouter(node=None)  # Returns 503, but we check kwargs
        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=fake_router,
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            creds = base64.b64encode(b"sr_live_abc123:").decode()
            writer.write(
                f"GET http://example.com/ HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"X-SpaceRouter-IP-Type: residential\r\n"
                f"X-SpaceRouter-Region: Seoul, KR\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            # Will get 503 because FakeNodeRouter returns None, but that's fine
            assert b"503" in response

            # Verify the routing headers were extracted and passed to select_node
            assert fake_router.last_select_kwargs["ip_type"] == "residential"
            assert fake_router.last_select_kwargs["ip_region"] == "Seoul, KR"

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_routing_headers_stripped_before_forwarding(self):
        """X-SpaceRouter-IP-Type and X-SpaceRouter-Region should NOT appear
        in the request forwarded to the home node."""
        received_headers = {}

        async def fake_node_handler(reader, writer):
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            # Parse the forwarded request headers
            header_section = data.split(b"\r\n\r\n")[0]
            for line in header_section.split(b"\r\n")[1:]:  # skip request line
                if b":" in line:
                    key, _, val = line.partition(b":")
                    received_headers[key.decode().strip().lower()] = val.decode().strip()

            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 2\r\n"
                b"\r\n"
                b"OK"
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        fake_node = await asyncio.start_server(fake_node_handler, "127.0.0.1", 0)
        node_port = fake_node.sockets[0].getsockname()[1]

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-1", endpoint_url=f"http://127.0.0.1:{node_port}")
            ),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = base64.b64encode(b"sr_live_abc123:").decode()
            writer.write(
                f"GET http://example.com/test HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"X-SpaceRouter-IP-Type: residential\r\n"
                f"X-SpaceRouter-Region: Seoul, KR\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            assert b"200 OK" in response

            # Verify routing headers were stripped before forwarding
            assert "x-spacerouter-ip-type" not in received_headers
            assert "x-spacerouter-region" not in received_headers
            # But Host should still be there
            assert "host" in received_headers

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            fake_node.close()
            await fake_node.wait_closed()

    @pytest.mark.asyncio
    async def test_no_routing_headers_passes_none(self):
        """Without routing headers, select_node gets ip_type=None, ip_region=None."""
        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        fake_router = FakeNodeRouter(node=None)
        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=fake_router,
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            creds = base64.b64encode(b"sr_live_abc123:").decode()
            writer.write(
                f"GET http://example.com/ HTTP/1.1\r\n"
                f"Host: example.com\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"503" in response

            # Without routing headers, both should be None
            assert fake_router.last_select_kwargs["ip_type"] is None
            assert fake_router.last_select_kwargs["ip_region"] is None

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestProxyServerCONNECT:
    @pytest.mark.asyncio
    async def test_connect_tunnel_with_mock_node(self):
        """Start a fake home node that accepts CONNECT, then tunnel data through."""
        async def fake_node_handler(reader, writer):
            # Read the CONNECT request
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk

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

        fake_node = await asyncio.start_server(fake_node_handler, "127.0.0.1", 0)
        node_port = fake_node.sockets[0].getsockname()[1]

        settings = Settings(
            PROXY_PORT=0,
            MANAGEMENT_PORT=0,
            COORDINATION_API_URL="http://test",
            COORDINATION_API_SECRET="s",
        )

        proxy = ProxyServer(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-1", endpoint_url=f"http://127.0.0.1:{node_port}")
            ),
            rate_limiter=RateLimiter(),
            request_logger=FakeRequestLogger(),
            settings=settings,
        )

        server = await proxy.start()
        proxy_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            creds = base64.b64encode(b"sr_live_abc123:").decode()
            writer.write(
                f"CONNECT example.com:443 HTTP/1.1\r\n"
                f"Host: example.com:443\r\n"
                f"Proxy-Authorization: Basic {creds}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            # Read the 200 response
            response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            response_str = response.decode("latin-1")
            assert "200 Connection Established" in response_str
            assert "X-SpaceRouter-Node: node-1" in response_str

            # Send data through tunnel and check it's echoed back
            writer.write(b"Hello through tunnel")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert echoed == b"Hello through tunnel"

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            fake_node.close()
            await fake_node.wait_closed()
