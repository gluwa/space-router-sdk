import asyncio
import base64
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from app.auth import AuthValidator, extract_api_key
from app.config import Settings
from app.errors import (
    bad_request,
    no_nodes_available,
    proxy_auth_required,
    rate_limited,
    upstream_error,
)
from app.logger import RequestLog, RequestLogger
from app.rate_limiter import RateLimiter
from app.routing import NodeRouter, NodeSelection

logger = logging.getLogger(__name__)

# Shared metrics counters (read by management.py)
metrics = {
    "total_requests": 0,
    "active_connections": 0,
    "auth_failures": 0,
    "rate_limited": 0,
    "upstream_errors": 0,
    "no_nodes": 0,
    "successful_requests": 0,
}


def parse_headers(raw: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in raw.split(b"\r\n"):
        if b":" in line:
            key, _, value = line.partition(b":")
            headers[key.decode("latin-1").strip()] = value.decode("latin-1").strip()
    return headers


async def _read_request_head(reader: asyncio.StreamReader) -> tuple[bytes, str, str, str, dict[str, str]] | None:
    try:
        request_line = await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=30.0)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
        return None

    parts = request_line.decode("latin-1").strip().split(" ", 2)
    if len(parts) != 3:
        return None

    method, target, version = parts

    # Read headers until blank line
    header_data = b""
    try:
        while True:
            line = await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=10.0)
            if line == b"\r\n":
                break
            header_data += line
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
        return None

    headers = parse_headers(header_data)
    raw_head = request_line + header_data + b"\r\n"
    return raw_head, method, target, version, headers


async def _pipe(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    counter: list[int],
    buffer_size: int,
) -> None:
    try:
        while True:
            data = await reader.read(buffer_size)
            if not data:
                break
            writer.write(data)
            await writer.drain()
            counter[0] += len(data)
    except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError):
        pass


async def relay_streams(
    reader_a: asyncio.StreamReader,
    writer_a: asyncio.StreamWriter,
    reader_b: asyncio.StreamReader,
    writer_b: asyncio.StreamWriter,
    buffer_size: int,
    timeout: float = 300.0,
) -> tuple[int, int]:
    bytes_a_to_b = [0]
    bytes_b_to_a = [0]

    task_a = asyncio.create_task(_pipe(reader_a, writer_b, bytes_a_to_b, buffer_size))
    task_b = asyncio.create_task(_pipe(reader_b, writer_a, bytes_b_to_a, buffer_size))

    try:
        await asyncio.wait_for(
            asyncio.gather(task_a, task_b, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        pass
    finally:
        task_a.cancel()
        task_b.cancel()
        try:
            await asyncio.gather(task_a, task_b, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    return bytes_a_to_b[0], bytes_b_to_a[0]


@dataclass
class NodeConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    proxy_auth: str | None  # Proxy-Authorization header value, if upstream proxy requires auth


def _extract_proxy_auth(parsed_url) -> str | None:
    """Extract Proxy-Authorization header from URL credentials (user:pass@host)."""
    if parsed_url.username:
        user = unquote(parsed_url.username)
        passwd = unquote(parsed_url.password or "")
        creds = base64.b64encode(f"{user}:{passwd}".encode()).decode()
        return f"Basic {creds}"
    return None


async def _connect_to_node(
    endpoint_url: str, timeout: float, tls_verify: bool = True
) -> NodeConnection | None:
    parsed = urlparse(endpoint_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    proxy_auth = _extract_proxy_auth(parsed)

    try:
        if parsed.scheme == "https":
            import ssl
            ctx = ssl.create_default_context()
            if not tls_verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=ctx),
                timeout=timeout,
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
        return NodeConnection(reader=reader, writer=writer, proxy_auth=proxy_auth)
    except Exception as e:
        logger.warning("Failed to connect to node %s: %s: %s", endpoint_url, type(e).__name__, e)
        return None


async def handle_connect(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
    node: NodeSelection,
    request_id: str,
    settings: Settings,
) -> tuple[bool, int, int, str | None]:
    conn = await _connect_to_node(
        node.endpoint_url, settings.NODE_REQUEST_TIMEOUT, settings.NODE_TLS_VERIFY
    )
    if conn is None:
        return False, 0, 0, "connection_refused"

    node_reader, node_writer = conn.reader, conn.writer

    try:
        # Send CONNECT to home node (or upstream proxy)
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

        # Read node response
        try:
            response_line = await asyncio.wait_for(
                node_reader.readuntil(b"\r\n"), timeout=settings.NODE_REQUEST_TIMEOUT
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return False, 0, 0, "timeout"

        # Read rest of headers
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

        # Tell client the tunnel is established
        response = (
            f"HTTP/1.1 200 Connection Established\r\n"
            f"X-SpaceRouter-Node: {node.node_id}\r\n"
            f"X-SpaceRouter-Request-Id: {request_id}\r\n"
            f"\r\n"
        ).encode()
        client_writer.write(response)
        await client_writer.drain()

        # Relay bytes bidirectionally
        bytes_sent, bytes_received = await relay_streams(
            client_reader, client_writer,
            node_reader, node_writer,
            buffer_size=65536,  # Using default buffer size since settings.BUFFER_SIZE might not exist
        )

        return True, bytes_sent, bytes_received, None

    finally:
        try:
            node_writer.close()
            await node_writer.wait_closed()
        except Exception:
            pass


async def handle_http_forward(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    method: str,
    target: str,
    version: str,
    headers: dict[str, str],
    node: NodeSelection,
    request_id: str,
    settings: Settings,
) -> tuple[bool, int, int, int | None, str | None]:
    conn = await _connect_to_node(
        node.endpoint_url, settings.NODE_REQUEST_TIMEOUT, settings.NODE_TLS_VERIFY
    )
    if conn is None:
        return False, 0, 0, None, "connection_refused"

    node_reader, node_writer = conn.reader, conn.writer

    try:
        # Build request to forward to home node (or upstream proxy)
        # Remove client's proxy-specific headers, keep the rest
        forward_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in ("proxy-authorization", "proxy-connection")
        }
        forward_headers["X-SpaceRouter-Request-Id"] = request_id
        # Add upstream proxy auth if the node endpoint has credentials
        if conn.proxy_auth:
            forward_headers["Proxy-Authorization"] = conn.proxy_auth

        header_str = "".join(f"{k}: {v}\r\n" for k, v in forward_headers.items())
        request_head = f"{method} {target} {version}\r\n{header_str}\r\n".encode()

        node_writer.write(request_head)
        await node_writer.drain()

        # Forward request body if present
        content_length = int(headers.get("Content-Length", headers.get("content-length", "0")))
        bytes_sent = len(request_head)
        buffer_size = 65536  # Using default buffer size
        
        if content_length > 0:
            remaining = content_length
            while remaining > 0:
                chunk = await client_reader.read(min(remaining, buffer_size))
                if not chunk:
                    break
                node_writer.write(chunk)
                await node_writer.drain()
                bytes_sent += len(chunk)
                remaining -= len(chunk)

        # Read response from node
        try:
            response_line = await asyncio.wait_for(
                node_reader.readuntil(b"\r\n"), timeout=settings.NODE_REQUEST_TIMEOUT
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return False, bytes_sent, 0, None, "timeout"

        resp_parts = response_line.decode("latin-1").strip().split(" ", 2)
        status_code = int(resp_parts[1]) if len(resp_parts) >= 2 else 0

        # Read response headers
        resp_header_data = b""
        while True:
            try:
                line = await asyncio.wait_for(node_reader.readuntil(b"\r\n"), timeout=10.0)
                if line == b"\r\n":
                    break
                resp_header_data += line
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break

        resp_headers = parse_headers(resp_header_data)

        # Inject X-SpaceRouter headers into response
        injected_headers = (
            f"X-SpaceRouter-Node: {node.node_id}\r\n"
            f"X-SpaceRouter-Request-Id: {request_id}\r\n"
        )

        # Write response to client: status line + original headers + injected headers + blank line
        client_writer.write(response_line)
        client_writer.write(resp_header_data)
        client_writer.write(injected_headers.encode())
        client_writer.write(b"\r\n")
        await client_writer.drain()

        bytes_received = len(response_line) + len(resp_header_data)

        # Relay response body
        resp_content_length = resp_headers.get("Content-Length", resp_headers.get("content-length"))
        transfer_encoding = resp_headers.get("Transfer-Encoding", resp_headers.get("transfer-encoding", ""))

        if resp_content_length:
            remaining = int(resp_content_length)
            while remaining > 0:
                chunk = await node_reader.read(min(remaining, buffer_size))
                if not chunk:
                    break
                client_writer.write(chunk)
                await client_writer.drain()
                bytes_received += len(chunk)
                remaining -= len(chunk)
        elif "chunked" in transfer_encoding.lower():
            # Relay chunked encoding as-is
            while True:
                try:
                    size_line = await asyncio.wait_for(
                        node_reader.readuntil(b"\r\n"), timeout=settings.NODE_REQUEST_TIMEOUT
                    )
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break
                client_writer.write(size_line)
                await client_writer.drain()
                bytes_received += len(size_line)

                chunk_size = int(size_line.strip(), 16)
                if chunk_size == 0:
                    # Read trailing CRLF
                    trailer = await node_reader.readuntil(b"\r\n")
                    client_writer.write(trailer)
                    await client_writer.drain()
                    break

                chunk_data = await node_reader.readexactly(chunk_size + 2)  # +2 for CRLF
                client_writer.write(chunk_data)
                await client_writer.drain()
                bytes_received += len(chunk_data)
        else:
            # No content-length or chunked: read until connection closes
            while True:
                chunk = await node_reader.read(buffer_size)
                if not chunk:
                    break
                client_writer.write(chunk)
                await client_writer.drain()
                bytes_received += len(chunk)

        return True, bytes_sent, bytes_received, status_code, None

    finally:
        try:
            node_writer.close()
            await node_writer.wait_closed()
        except Exception:
            pass


class ProxyServer:
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
            port=self.settings.PROXY_PORT,
        )
        logger.info("Proxy server listening on port %d", self.settings.PROXY_PORT)
        return self._server

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        metrics["total_requests"] += 1
        metrics["active_connections"] += 1
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()

        try:
            result = await _read_request_head(reader)
            if result is None:
                writer.write(bad_request("Malformed request", request_id))
                await writer.drain()
                return

            raw_head, method, target, version, headers = result

            # --- Authentication ---
            # Get Proxy-Authorization header - use get() for dictionary access
            auth_header = headers.get("Proxy-Authorization", "")
            
            try:
                api_key = extract_api_key(auth_header)
            except Exception as e:
                logger.error(f"Error extracting API key: {e}")
                metrics["auth_failures"] += 1
                writer.write(proxy_auth_required(request_id))
                await writer.drain()
                return
            
            if not api_key:
                metrics["auth_failures"] += 1
                writer.write(proxy_auth_required(request_id))
                await writer.drain()
                return

            auth_result = await self.auth_validator.validate(api_key)
            if not auth_result:
                metrics["auth_failures"] += 1
                writer.write(proxy_auth_required(request_id))
                await writer.drain()
                return

            api_key_id = auth_result.api_key_id or ""
            rpm_limit = auth_result.rate_limit_rpm or self.settings.DEFAULT_RATE_LIMIT_RPM

            # --- Rate Limiting ---
            allowed, retry_after = await self.rate_limiter.check(api_key_id, rpm_limit)
            if not allowed:
                metrics["rate_limited"] += 1
                writer.write(rate_limited(retry_after, request_id))
                await writer.drain()
                return

            # --- Node Selection ---
            node = await self.node_router.select_node()
            if node is None:
                metrics["no_nodes"] += 1
                writer.write(no_nodes_available(request_id))
                await writer.drain()
                return

            # --- Route Request ---
            if method.upper() == "CONNECT":
                # CONNECT host:port
                host_port = target.split(":")
                target_host = host_port[0]
                target_port = int(host_port[1]) if len(host_port) > 1 else 443

                success, bytes_sent, bytes_received, error_type = await handle_connect(
                    reader, writer, target_host, target_port, node, request_id, self.settings,
                )

                if not success:
                    # Retry with alternate node
                    alt_node = await self.node_router.select_node()
                    if alt_node and alt_node.node_id != node.node_id:
                        self.node_router.report_outcome(node.node_id, False, 0, 0)
                        success, bytes_sent, bytes_received, error_type = await handle_connect(
                            reader, writer, target_host, target_port, alt_node, request_id, self.settings,
                        )
                        node = alt_node

                    if not success:
                        metrics["upstream_errors"] += 1
                        writer.write(upstream_error(request_id, node.node_id))
                        await writer.drain()

                latency_ms = int((time.monotonic() - start_time) * 1000)
                self.node_router.report_outcome(node.node_id, success, latency_ms, bytes_sent + bytes_received)

                if success:
                    metrics["successful_requests"] += 1

                self.request_logger.log(RequestLog(
                    request_id=request_id,
                    api_key_id=api_key_id,
                    node_id=node.node_id,
                    method="CONNECT",
                    target_host=target_host,
                    status_code=200 if success else 502,
                    bytes_sent=bytes_sent,
                    bytes_received=bytes_received,
                    latency_ms=latency_ms,
                    success=success,
                    error_type=error_type,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ))

            else:
                # HTTP forward proxy
                parsed = urlparse(target)
                target_host = parsed.hostname or target

                success, bytes_sent, bytes_received, status_code, error_type = await handle_http_forward(
                    reader, writer, method, target, version, headers, node, request_id, self.settings,
                )

                if not success:
                    # Retry with alternate node
                    alt_node = await self.node_router.select_node()
                    if alt_node and alt_node.node_id != node.node_id:
                        self.node_router.report_outcome(node.node_id, False, 0, 0)
                        success, bytes_sent, bytes_received, status_code, error_type = await handle_http_forward(
                            reader, writer, method, target, version, headers, alt_node, request_id, self.settings,
                        )
                        node = alt_node

                    if not success:
                        metrics["upstream_errors"] += 1
                        writer.write(upstream_error(request_id, node.node_id))
                        await writer.drain()

                latency_ms = int((time.monotonic() - start_time) * 1000)

                # Inject latency header only for HTTP forward (CONNECT already sent 200)
                if success:
                    metrics["successful_requests"] += 1

                self.node_router.report_outcome(node.node_id, success, latency_ms, bytes_sent + bytes_received)

                self.request_logger.log(RequestLog(
                    request_id=request_id,
                    api_key_id=api_key_id,
                    node_id=node.node_id,
                    method=method,
                    target_host=target_host,
                    status_code=status_code,
                    bytes_sent=bytes_sent,
                    bytes_received=bytes_received,
                    latency_ms=latency_ms,
                    success=success,
                    error_type=error_type,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ))

        except Exception as e:
            logger.exception(f"Unhandled error in proxy handler: {e}")
        finally:
            metrics["active_connections"] -= 1
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass