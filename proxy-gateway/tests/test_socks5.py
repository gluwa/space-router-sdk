import asyncio
import socket
import struct

import pytest

from app.auth import AuthResult
from app.config import Settings
from app.rate_limiter import RateLimiter
from app.routing import NodeSelection
from app.socks5 import (
    ATYP_DOMAIN,
    ATYP_IPV4,
    ATYP_IPV6,
    AUTH_NO_ACCEPTABLE,
    AUTH_NONE,
    AUTH_USERNAME_PASSWORD,
    CMD_BIND,
    CMD_CONNECT,
    CMD_UDP_ASSOCIATE,
    REP_COMMAND_NOT_SUPPORTED,
    REP_HOST_UNREACHABLE,
    REP_NETWORK_UNREACHABLE,
    REP_SUCCESS,
    SOCKS_VERSION,
    Socks5Server,
)


# --- Fakes (same pattern as test_proxy.py) ---


class FakeAuthValidator:
    _DEFAULT = AuthResult(valid=True, api_key_id="test-key-id", rate_limit_rpm=60)

    def __init__(self, result: AuthResult | None = _DEFAULT):
        self._result = result

    async def validate(self, api_key: str) -> AuthResult | None:
        return self._result


class FakeNodeRouter:
    def __init__(self, node: NodeSelection | None = None):
        self._node = node
        self.reports: list[dict] = []

    async def select_node(self, *, ip_type=None, ip_region=None) -> NodeSelection | None:
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


# --- Helpers ---


def _make_settings(**overrides) -> Settings:
    defaults = {
        "PROXY_PORT": 0,
        "SOCKS5_PORT": 0,
        "MANAGEMENT_PORT": 0,
        "COORDINATION_API_URL": "http://test",
        "COORDINATION_API_SECRET": "s",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _greeting(*methods: int) -> bytes:
    """Build a SOCKS5 client greeting."""
    return struct.pack("!BB", SOCKS_VERSION, len(methods)) + bytes(methods)


def _auth_request(username: str, password: str = "") -> bytes:
    """Build a SOCKS5 username/password auth request (RFC 1929)."""
    udata = username.encode("utf-8")
    pdata = password.encode("utf-8")
    return struct.pack("!B", 0x01) + struct.pack("!B", len(udata)) + udata + struct.pack("!B", len(pdata)) + pdata


def _connect_request_domain(host: str, port: int) -> bytes:
    """Build a SOCKS5 CONNECT request with domain address."""
    hdata = host.encode("ascii")
    return struct.pack("!BBBB", SOCKS_VERSION, CMD_CONNECT, 0x00, ATYP_DOMAIN) + struct.pack("!B", len(hdata)) + hdata + struct.pack("!H", port)


def _connect_request_ipv4(ip: str, port: int) -> bytes:
    """Build a SOCKS5 CONNECT request with IPv4 address."""
    return struct.pack("!BBBB", SOCKS_VERSION, CMD_CONNECT, 0x00, ATYP_IPV4) + socket.inet_aton(ip) + struct.pack("!H", port)


def _connect_request_ipv6(ip: str, port: int) -> bytes:
    """Build a SOCKS5 CONNECT request with IPv6 address."""
    return struct.pack("!BBBB", SOCKS_VERSION, CMD_CONNECT, 0x00, ATYP_IPV6) + socket.inet_pton(socket.AF_INET6, ip) + struct.pack("!H", port)


def _command_request(cmd: int, host: str = "example.com", port: int = 443) -> bytes:
    """Build a SOCKS5 request with arbitrary command."""
    hdata = host.encode("ascii")
    return struct.pack("!BBBB", SOCKS_VERSION, cmd, 0x00, ATYP_DOMAIN) + struct.pack("!B", len(hdata)) + hdata + struct.pack("!H", port)


async def _start_socks5_server(auth_validator=None, node_router=None, rate_limiter=None, **settings_kw):
    """Helper to start a Socks5Server with fakes and return (server, port)."""
    settings = _make_settings(**settings_kw)
    socks = Socks5Server(
        auth_validator=auth_validator or FakeAuthValidator(),
        node_router=node_router or FakeNodeRouter(),
        rate_limiter=rate_limiter or RateLimiter(),
        request_logger=FakeRequestLogger(),
        settings=settings,
    )
    server = await socks.start()
    port = server.sockets[0].getsockname()[1]
    return server, port, socks


# --- Tests ---


class TestSocks5Greeting:
    @pytest.mark.asyncio
    async def test_valid_greeting_selects_username_password(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_greeting(AUTH_NONE, AUTH_USERNAME_PASSWORD))
            await writer.drain()

            resp = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            ver, method = struct.unpack("!BB", resp)
            assert ver == SOCKS_VERSION
            assert method == AUTH_USERNAME_PASSWORD

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_no_acceptable_method(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_greeting(AUTH_NONE))  # Only no-auth, we require username/password
            await writer.drain()

            resp = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            ver, method = struct.unpack("!BB", resp)
            assert ver == SOCKS_VERSION
            assert method == AUTH_NO_ACCEPTABLE

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_wrong_version_closes_connection(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(struct.pack("!BB", 0x04, 1) + bytes([AUTH_USERNAME_PASSWORD]))  # SOCKS4
            await writer.drain()

            # Server should close the connection without responding
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert data == b""

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestSocks5Auth:
    @pytest.mark.asyncio
    async def test_valid_api_key(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            # Greeting
            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            # Auth
            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            ver, status = struct.unpack("!BB", resp)
            assert ver == 0x01
            assert status == 0x00  # success

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_invalid_api_key(self):
        server, port, _ = await _start_socks5_server(
            auth_validator=FakeAuthValidator(None),  # Auth always fails
        )
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("bad_key"))
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            ver, status = struct.unpack("!BB", resp)
            assert ver == 0x01
            assert status == 0x01  # failure

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_empty_username(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request(""))  # empty username
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(2), timeout=5.0)
            ver, status = struct.unpack("!BB", resp)
            assert status == 0x01  # failure

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestSocks5UnsupportedCommands:
    @pytest.mark.asyncio
    async def test_bind_rejected(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_command_request(CMD_BIND))
            await writer.drain()

            resp = await asyncio.wait_for(reader.readexactly(10), timeout=5.0)
            assert resp[1] == REP_COMMAND_NOT_SUPPORTED

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_udp_associate_rejected(self):
        server, port, _ = await _start_socks5_server()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_command_request(CMD_UDP_ASSOCIATE))
            await writer.drain()

            resp = await asyncio.wait_for(reader.readexactly(10), timeout=5.0)
            assert resp[1] == REP_COMMAND_NOT_SUPPORTED

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestSocks5NoNodes:
    @pytest.mark.asyncio
    async def test_no_nodes_returns_network_unreachable(self):
        server, port, _ = await _start_socks5_server(
            node_router=FakeNodeRouter(node=None),
        )
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_connect_request_domain("example.com", 443))
            await writer.drain()

            resp = await asyncio.wait_for(reader.readexactly(10), timeout=5.0)
            assert resp[1] == REP_NETWORK_UNREACHABLE

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestSocks5RateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit(self):
        rate_limiter = RateLimiter()
        server, port, _ = await _start_socks5_server(
            auth_validator=FakeAuthValidator(AuthResult(valid=True, api_key_id="key1", rate_limit_rpm=1)),
            node_router=FakeNodeRouter(node=None),  # Will hit no-nodes after rate check
            rate_limiter=rate_limiter,
        )
        try:
            # First request: passes rate limit, gets network_unreachable (no nodes)
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(_greeting(AUTH_USERNAME_PASSWORD))
            await w.drain()
            await r.readexactly(2)
            w.write(_auth_request("sr_live_abc123"))
            await w.drain()
            await r.readexactly(2)
            w.write(_connect_request_domain("example.com", 443))
            await w.drain()
            resp = await asyncio.wait_for(r.readexactly(10), timeout=5.0)
            assert resp[1] == REP_NETWORK_UNREACHABLE  # no nodes, but passed rate limit
            w.close()
            await w.wait_closed()

            # Second request: should be rate limited (general failure)
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(_greeting(AUTH_USERNAME_PASSWORD))
            await w.drain()
            await r.readexactly(2)
            w.write(_auth_request("sr_live_abc123"))
            await w.drain()
            await r.readexactly(2)
            w.write(_connect_request_domain("example.com", 443))
            await w.drain()
            resp = await asyncio.wait_for(r.readexactly(10), timeout=5.0)
            # REP_GENERAL_FAILURE = 0x01 for rate limiting
            assert resp[1] == 0x01

            w.close()
            await w.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class TestSocks5ConnectTunnel:
    @pytest.mark.asyncio
    async def test_connect_domain_with_echo_node(self):
        """Full SOCKS5 CONNECT with domain address, tunneled through fake home node."""
        async def fake_node_handler(reader, writer):
            # Read the CONNECT request from gateway
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk

            # Verify it's a CONNECT request
            assert b"CONNECT example.com:443 HTTP/1.1" in data

            # Respond with 200
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

        fake_logger = FakeRequestLogger()
        socks_settings = _make_settings()
        socks = Socks5Server(
            auth_validator=FakeAuthValidator(),
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-1", endpoint_url=f"http://127.0.0.1:{node_port}"),
            ),
            rate_limiter=RateLimiter(),
            request_logger=fake_logger,
            settings=socks_settings,
        )
        server = await socks.start()
        socks_port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", socks_port)

            # Greeting
            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            resp = await reader.readexactly(2)
            assert resp == struct.pack("!BB", SOCKS_VERSION, AUTH_USERNAME_PASSWORD)

            # Auth
            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            resp = await reader.readexactly(2)
            assert resp == struct.pack("!BB", 0x01, 0x00)

            # CONNECT
            writer.write(_connect_request_domain("example.com", 443))
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(10), timeout=5.0)
            assert resp[1] == REP_SUCCESS

            # Send data through tunnel and verify echo
            writer.write(b"Hello SOCKS5!")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert echoed == b"Hello SOCKS5!"

            writer.close()
            await writer.wait_closed()
        finally:
            # Wait for handler to finish logging before closing server
            await asyncio.sleep(0.3)
            server.close()
            await server.wait_closed()
            fake_node.close()
            await fake_node.wait_closed()

        # Verify logging after server shutdown
        assert len(fake_logger.logs) == 1
        log = fake_logger.logs[0]
        assert log.success is True
        assert log.method == "SOCKS5_CONNECT"
        assert log.target_host == "example.com"
        assert log.node_id == "node-1"

    @pytest.mark.asyncio
    async def test_connect_ipv4(self):
        """SOCKS5 CONNECT with IPv4 address type."""
        async def fake_node_handler(reader, writer):
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk

            assert b"CONNECT 93.184.216.34:80 HTTP/1.1" in data

            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

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

        server, socks_port, _ = await _start_socks5_server(
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-1", endpoint_url=f"http://127.0.0.1:{node_port}"),
            ),
        )

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", socks_port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_connect_request_ipv4("93.184.216.34", 80))
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(10), timeout=5.0)
            assert resp[1] == REP_SUCCESS

            writer.write(b"ping")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert echoed == b"ping"

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            fake_node.close()
            await fake_node.wait_closed()

    @pytest.mark.asyncio
    async def test_connect_ipv6(self):
        """SOCKS5 CONNECT with IPv6 address type."""
        async def fake_node_handler(reader, writer):
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk

            # IPv6 ::1 should appear in the CONNECT line
            assert b"CONNECT ::1:80 HTTP/1.1" in data

            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

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

        server, socks_port, _ = await _start_socks5_server(
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-1", endpoint_url=f"http://127.0.0.1:{node_port}"),
            ),
        )

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", socks_port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_connect_request_ipv6("::1", 80))
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(10), timeout=5.0)
            assert resp[1] == REP_SUCCESS

            writer.write(b"ipv6-test")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert echoed == b"ipv6-test"

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
            fake_node.close()
            await fake_node.wait_closed()

    @pytest.mark.asyncio
    async def test_node_failure_returns_host_unreachable(self):
        """When node connection fails, SOCKS5 should return REP_HOST_UNREACHABLE."""
        # Use a node endpoint that won't connect (port 1 is almost certainly closed)
        server, socks_port, _ = await _start_socks5_server(
            node_router=FakeNodeRouter(
                node=NodeSelection(node_id="node-bad", endpoint_url="http://127.0.0.1:1"),
            ),
            NODE_REQUEST_TIMEOUT=1.0,
        )

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", socks_port)

            writer.write(_greeting(AUTH_USERNAME_PASSWORD))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_auth_request("sr_live_abc123"))
            await writer.drain()
            await reader.readexactly(2)

            writer.write(_connect_request_domain("example.com", 443))
            await writer.drain()
            resp = await asyncio.wait_for(reader.readexactly(10), timeout=10.0)
            assert resp[1] == REP_HOST_UNREACHABLE

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
