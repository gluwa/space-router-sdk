"""SOCKS5 proxy server (RFC 1928 + RFC 1929 username/password auth).

Accepts SOCKS5 CONNECT requests from clients and tunnels them through
home nodes using the same HTTP CONNECT mechanism as the HTTP proxy.
"""

import asyncio
import logging
import socket
import struct
import time
import uuid
from datetime import datetime, timezone

from app.auth import AuthValidator
from app.config import Settings
from app.logger import RequestLog, RequestLogger
from app.proxy import NodeConnection, _connect_to_node, metrics, relay_streams
from app.rate_limiter import RateLimiter
from app.routing import NodeRouter

logger = logging.getLogger(__name__)

# SOCKS5 constants (RFC 1928)
SOCKS_VERSION = 0x05
AUTH_NONE = 0x00
AUTH_USERNAME_PASSWORD = 0x02
AUTH_NO_ACCEPTABLE = 0xFF

# Username/password auth (RFC 1929)
AUTH_SUB_VERSION = 0x01

# Commands
CMD_CONNECT = 0x01
CMD_BIND = 0x02
CMD_UDP_ASSOCIATE = 0x03

# Address types
ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04

# Reply codes
REP_SUCCESS = 0x00
REP_GENERAL_FAILURE = 0x01
REP_NOT_ALLOWED = 0x02
REP_NETWORK_UNREACHABLE = 0x03
REP_HOST_UNREACHABLE = 0x04
REP_CONNECTION_REFUSED = 0x05
REP_COMMAND_NOT_SUPPORTED = 0x07
REP_ADDRESS_TYPE_NOT_SUPPORTED = 0x08

# Timeouts
HANDSHAKE_TIMEOUT = 30.0
AUTH_TIMEOUT = 10.0


def _build_reply(reply_code: int) -> bytes:
    """Build a SOCKS5 reply with bind address 0.0.0.0:0."""
    return struct.pack(
        "!BBBB4sH",
        SOCKS_VERSION,
        reply_code,
        0x00,  # reserved
        ATYP_IPV4,
        b"\x00\x00\x00\x00",  # bind addr
        0,  # bind port
    )


class Socks5Server:
    def __init__(
        self,
        auth_validator: AuthValidator,
        node_router: NodeRouter,
        rate_limiter: RateLimiter,
        request_logger: RequestLogger,
        settings: Settings,
    ) -> None:
        self.auth_validator = auth_validator
        self.node_router = node_router
        self.rate_limiter = rate_limiter
        self.request_logger = request_logger
        self.settings = settings
        self._server: asyncio.Server | None = None

    async def start(self) -> asyncio.Server:
        self._server = await asyncio.start_server(
            self._handle_client,
            host="0.0.0.0",
            port=self.settings.SOCKS5_PORT,
        )
        logger.info("SOCKS5 server listening on port %d", self.settings.SOCKS5_PORT)
        return self._server

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        metrics["socks5_total_requests"] += 1
        metrics["socks5_active_connections"] += 1
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()
        api_key_id = ""
        target_host = ""
        node_id: str | None = None
        success = False
        bytes_sent = 0
        bytes_received = 0
        error_type: str | None = None

        try:
            # === Greeting (RFC 1928 §4) ===
            header = await asyncio.wait_for(reader.readexactly(2), timeout=HANDSHAKE_TIMEOUT)
            version, nmethods = struct.unpack("!BB", header)
            if version != SOCKS_VERSION:
                return

            methods = await asyncio.wait_for(reader.readexactly(nmethods), timeout=AUTH_TIMEOUT)

            if AUTH_USERNAME_PASSWORD not in methods:
                writer.write(struct.pack("!BB", SOCKS_VERSION, AUTH_NO_ACCEPTABLE))
                await writer.drain()
                return

            writer.write(struct.pack("!BB", SOCKS_VERSION, AUTH_USERNAME_PASSWORD))
            await writer.drain()

            # === Username/Password Auth (RFC 1929) ===
            auth_ver = struct.unpack("!B", await asyncio.wait_for(reader.readexactly(1), timeout=AUTH_TIMEOUT))[0]
            if auth_ver != AUTH_SUB_VERSION:
                writer.write(struct.pack("!BB", AUTH_SUB_VERSION, 0x01))
                await writer.drain()
                return

            ulen = struct.unpack("!B", await asyncio.wait_for(reader.readexactly(1), timeout=AUTH_TIMEOUT))[0]
            username = (await asyncio.wait_for(reader.readexactly(ulen), timeout=AUTH_TIMEOUT)).decode("utf-8")
            plen = struct.unpack("!B", await asyncio.wait_for(reader.readexactly(1), timeout=AUTH_TIMEOUT))[0]
            if plen > 0:
                await asyncio.wait_for(reader.readexactly(plen), timeout=AUTH_TIMEOUT)  # read and discard password

            api_key = username
            if not api_key:
                metrics["socks5_auth_failures"] += 1
                writer.write(struct.pack("!BB", AUTH_SUB_VERSION, 0x01))
                await writer.drain()
                return

            auth_result = await self.auth_validator.validate(api_key)
            if not auth_result:
                metrics["socks5_auth_failures"] += 1
                writer.write(struct.pack("!BB", AUTH_SUB_VERSION, 0x01))
                await writer.drain()
                return

            writer.write(struct.pack("!BB", AUTH_SUB_VERSION, 0x00))
            await writer.drain()

            api_key_id = auth_result.api_key_id or ""
            rpm_limit = auth_result.rate_limit_rpm or self.settings.DEFAULT_RATE_LIMIT_RPM

            # === Rate Limiting ===
            allowed, _retry_after = await self.rate_limiter.check(api_key_id, rpm_limit)
            if not allowed:
                metrics["rate_limited"] += 1
                writer.write(_build_reply(REP_GENERAL_FAILURE))
                await writer.drain()
                return

            # === Request (RFC 1928 §4) ===
            req_header = await asyncio.wait_for(reader.readexactly(4), timeout=AUTH_TIMEOUT)
            ver, cmd, _rsv, atyp = struct.unpack("!BBBB", req_header)

            if ver != SOCKS_VERSION:
                writer.write(_build_reply(REP_GENERAL_FAILURE))
                await writer.drain()
                return

            if cmd != CMD_CONNECT:
                writer.write(_build_reply(REP_COMMAND_NOT_SUPPORTED))
                await writer.drain()
                return

            # Parse destination address
            if atyp == ATYP_IPV4:
                raw_addr = await asyncio.wait_for(reader.readexactly(4), timeout=AUTH_TIMEOUT)
                target_host = socket.inet_ntoa(raw_addr)
            elif atyp == ATYP_DOMAIN:
                domain_len = struct.unpack("!B", await asyncio.wait_for(reader.readexactly(1), timeout=AUTH_TIMEOUT))[0]
                target_host = (await asyncio.wait_for(reader.readexactly(domain_len), timeout=AUTH_TIMEOUT)).decode("ascii")
            elif atyp == ATYP_IPV6:
                raw_addr = await asyncio.wait_for(reader.readexactly(16), timeout=AUTH_TIMEOUT)
                target_host = socket.inet_ntop(socket.AF_INET6, raw_addr)
            else:
                writer.write(_build_reply(REP_ADDRESS_TYPE_NOT_SUPPORTED))
                await writer.drain()
                return

            target_port = struct.unpack("!H", await asyncio.wait_for(reader.readexactly(2), timeout=AUTH_TIMEOUT))[0]

            logger.debug("[%s] SOCKS5 CONNECT %s:%d", request_id[:8], target_host, target_port)

            # === Node Selection ===
            node = await self.node_router.select_node()
            if node is None:
                metrics["no_nodes"] += 1
                writer.write(_build_reply(REP_NETWORK_UNREACHABLE))
                await writer.drain()
                error_type = "no_nodes"
                return

            node_id = node.node_id

            # === Connect through Home Node ===
            success, bytes_sent, bytes_received, error_type = await self._tunnel_through_node(
                reader, writer, target_host, target_port, node, request_id,
            )

            if not success:
                # Retry with alternate node
                alt_node = await self.node_router.select_node()
                if alt_node and alt_node.node_id != node.node_id:
                    self.node_router.report_outcome(node.node_id, False, 0, 0)
                    node = alt_node
                    node_id = alt_node.node_id
                    success, bytes_sent, bytes_received, error_type = await self._tunnel_through_node(
                        reader, writer, target_host, target_port, alt_node, request_id,
                    )

                if not success:
                    metrics["upstream_errors"] += 1
                    writer.write(_build_reply(REP_HOST_UNREACHABLE))
                    await writer.drain()

            if success:
                metrics["socks5_successful_requests"] += 1

        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            logger.debug("[%s] SOCKS5 handshake timeout/incomplete", request_id[:8])
            error_type = "timeout"
        except (ConnectionResetError, BrokenPipeError, OSError):
            logger.debug("[%s] SOCKS5 connection reset", request_id[:8])
            error_type = "connection_reset"
        except struct.error:
            logger.debug("[%s] SOCKS5 malformed packet", request_id[:8])
            error_type = "malformed"
        except Exception as e:
            logger.exception("[%s] Unhandled error in SOCKS5 handler: %s", request_id[:8], e)
            error_type = "internal_error"
        finally:
            metrics["socks5_active_connections"] -= 1

            latency_ms = int((time.monotonic() - start_time) * 1000)
            if node_id:
                self.node_router.report_outcome(node_id, success, latency_ms, bytes_sent + bytes_received)

            if target_host:
                self.request_logger.log(RequestLog(
                    request_id=request_id,
                    api_key_id=api_key_id,
                    node_id=node_id,
                    method="SOCKS5_CONNECT",
                    target_host=target_host,
                    status_code=200 if success else 502,
                    bytes_sent=bytes_sent,
                    bytes_received=bytes_received,
                    latency_ms=latency_ms,
                    success=success,
                    error_type=error_type,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ))

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _tunnel_through_node(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        target_host: str,
        target_port: int,
        node: "NodeRouter",
        request_id: str,
    ) -> tuple[bool, int, int, str | None]:
        """Establish tunnel through home node and relay data."""
        conn = await _connect_to_node(node.endpoint_url, self.settings.NODE_REQUEST_TIMEOUT)
        if conn is None:
            return False, 0, 0, "connection_refused"

        node_reader, node_writer = conn.reader, conn.writer

        try:
            # Send HTTP CONNECT to home node
            auth_header = f"Proxy-Authorization: {conn.proxy_auth}\r\n" if conn.proxy_auth else ""
            connect_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"{auth_header}"
                f"X-SpaceRouter-Request-Id: {request_id}\r\n"
                f"\r\n"
            ).encode()
            node_writer.write(connect_req)
            await node_writer.drain()

            # Read response from home node
            try:
                response_line = await asyncio.wait_for(
                    node_reader.readuntil(b"\r\n"), timeout=self.settings.NODE_REQUEST_TIMEOUT
                )
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                return False, 0, 0, "timeout"

            # Consume remaining headers
            while True:
                try:
                    line = await asyncio.wait_for(node_reader.readuntil(b"\r\n"), timeout=5.0)
                    if line == b"\r\n":
                        break
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

            status_code = int(response_line.decode("latin-1").split(" ", 2)[1])
            if status_code != 200:
                return False, 0, 0, "node_error"

            # Tell SOCKS5 client the connection is established
            client_writer.write(_build_reply(REP_SUCCESS))
            await client_writer.drain()

            # Bidirectional relay
            bytes_sent, bytes_received = await relay_streams(
                client_reader, client_writer,
                node_reader, node_writer,
                buffer_size=65536,
            )

            return True, bytes_sent, bytes_received, None

        finally:
            try:
                node_writer.close()
                await node_writer.wait_closed()
            except Exception:
                pass
