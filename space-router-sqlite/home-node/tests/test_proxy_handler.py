"""Tests for the Home Node proxy handler.

Each test starts a real asyncio TCP server (home-node) and a fake target
server, then sends requests through the home-node and asserts on the result.
"""

import asyncio
import functools

import pytest

from app.proxy_handler import handle_client, parse_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_home_node(settings):
    """Start the home-node TCP server on a random port; return (server, port)."""
    handler = functools.partial(handle_client, settings=settings)
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _start_target_server(handler):
    """Start a fake target server; return (server, port)."""
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


# ---------------------------------------------------------------------------
# parse_headers
# ---------------------------------------------------------------------------

class TestParseHeaders:
    def test_basic(self):
        raw = b"Host: example.com\r\nContent-Type: text/html\r\n"
        h = parse_headers(raw)
        assert h["Host"] == "example.com"
        assert h["Content-Type"] == "text/html"

    def test_empty(self):
        assert parse_headers(b"") == {}


# ---------------------------------------------------------------------------
# CONNECT tunnel
# ---------------------------------------------------------------------------

class TestConnectTunnel:
    @pytest.mark.asyncio
    async def test_connect_tunnel_echo(self, settings):
        """CONNECT through home-node → target echoes data back."""

        async def echo_handler(reader, writer):
            try:
                while True:
                    data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except (asyncio.TimeoutError, ConnectionResetError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        target, target_port = await _start_target_server(echo_handler)
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)

            # Send CONNECT to home-node
            writer.write(
                f"CONNECT 127.0.0.1:{target_port} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{target_port}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            # Expect 200 Connection Established
            resp = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            assert b"200 Connection Established" in resp

            # Send data through the tunnel
            writer.write(b"ping")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert echoed == b"ping"

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()
            target.close()
            await target.wait_closed()

    @pytest.mark.asyncio
    async def test_connect_target_unreachable(self, settings):
        """CONNECT to a port with nothing listening → 502 Bad Gateway."""
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)
            writer.write(
                b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n"
                b"Host: 127.0.0.1:1\r\n"
                b"\r\n"
            )
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"502" in resp
            assert b"Bad Gateway" in resp

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()


# ---------------------------------------------------------------------------
# HTTP forward
# ---------------------------------------------------------------------------

class TestHTTPForward:
    @pytest.mark.asyncio
    async def test_http_forward_get(self, settings):
        """HTTP GET through home-node → target returns 200 + body."""

        async def target_handler(reader, writer):
            # Read the forwarded request
            await asyncio.wait_for(reader.read(4096), timeout=5.0)
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

        target, target_port = await _start_target_server(target_handler)
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)
            writer.write(
                f"GET http://127.0.0.1:{target_port}/test HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{target_port}\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            text = resp.decode("latin-1")
            assert "200 OK" in text
            assert "OK" in text

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()
            target.close()
            await target.wait_closed()

    @pytest.mark.asyncio
    async def test_http_forward_post_with_body(self, settings):
        """HTTP POST with a body is forwarded correctly."""
        received_body = []

        async def target_handler(reader, writer):
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            # Extract body after \r\n\r\n
            if b"\r\n\r\n" in data:
                body = data.split(b"\r\n\r\n", 1)[1]
                received_body.append(body)
            response = (
                b"HTTP/1.1 201 Created\r\n"
                b"Content-Length: 7\r\n"
                b"\r\n"
                b"created"
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        target, target_port = await _start_target_server(target_handler)
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)
            body = b'{"key": "value"}'
            writer.write(
                f"POST http://127.0.0.1:{target_port}/data HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{target_port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n".encode() + body
            )
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            text = resp.decode("latin-1")
            assert "201 Created" in text
            assert "created" in text

            # Verify the target received the body
            assert len(received_body) == 1
            assert received_body[0] == body

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()
            target.close()
            await target.wait_closed()

    @pytest.mark.asyncio
    async def test_http_forward_target_unreachable(self, settings):
        """HTTP forward to unreachable target → 502 Bad Gateway."""
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)
            writer.write(
                b"GET http://127.0.0.1:1/nope HTTP/1.1\r\n"
                b"Host: 127.0.0.1:1\r\n"
                b"\r\n"
            )
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"502" in resp
            assert b"Bad Gateway" in resp

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()


# ---------------------------------------------------------------------------
# Malformed request
# ---------------------------------------------------------------------------

class TestMalformed:
    @pytest.mark.asyncio
    async def test_malformed_request(self, settings):
        """Sending garbage → 400 Bad Request."""
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)
            writer.write(b"NOT_VALID\r\n\r\n")
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            assert b"400" in resp
            assert b"Bad Request" in resp

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()


# ---------------------------------------------------------------------------
# X-SpaceRouter header stripping
# ---------------------------------------------------------------------------

class TestHeaderStripping:
    @pytest.mark.asyncio
    async def test_spacerouter_headers_stripped(self, settings):
        """X-SpaceRouter-* and Proxy-Authorization headers must NOT reach the target."""
        received_headers = {}

        async def target_handler(reader, writer):
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            # Parse all headers from the forwarded request
            head = data.split(b"\r\n\r\n")[0]
            lines = head.split(b"\r\n")[1:]  # skip request line
            for line in lines:
                if b":" in line:
                    k, _, v = line.partition(b":")
                    received_headers[k.decode().strip().lower()] = v.decode().strip()

            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 2\r\n"
                b"\r\n"
                b"OK"
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        target, target_port = await _start_target_server(target_handler)
        home, home_port = await _start_home_node(settings)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", home_port)
            writer.write(
                f"GET http://127.0.0.1:{target_port}/check HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{target_port}\r\n"
                f"X-SpaceRouter-Request-Id: abc123\r\n"
                f"Proxy-Authorization: Basic dGVzdDp0ZXN0\r\n"
                f"\r\n".encode()
            )
            await writer.drain()

            await asyncio.wait_for(reader.read(4096), timeout=5.0)

            # These headers should have been stripped by the home-node
            assert "x-spacerouter-request-id" not in received_headers
            assert "proxy-authorization" not in received_headers
            # But Host should still be there
            assert "host" in received_headers

            writer.close()
            await writer.wait_closed()
        finally:
            home.close()
            await home.wait_closed()
            target.close()
            await target.wait_closed()
