"""Tailscale integration for the Home Node.

Detects the Tailscale IPv4 address and optionally authenticates
the node to a tailnet using an auth key.
"""

import asyncio
import json
import logging
import socket

logger = logging.getLogger(__name__)

# macOS and Linux both use this path for the CLI-installed daemon.
# The macOS App Store version uses a different path handled in the fallback.
_TAILSCALE_SOCK_PATHS = [
    "/var/run/tailscale/tailscaled.sock",
    # macOS App Store Tailscale
    "/Library/Group Containers/io.tailscale.ipn.macos/tailscaled.sock",
]


async def detect_tailscale_ip() -> str | None:
    """Detect the Tailscale IPv4 address.

    Tries the local API socket first, then falls back to the CLI.
    Returns ``None`` if Tailscale is not running or not connected.
    """
    ip = await _detect_via_local_api()
    if ip:
        return ip
    return await _detect_via_cli()


async def _detect_via_local_api() -> str | None:
    """Query the Tailscale local API via Unix socket."""
    for sock_path in _TAILSCALE_SOCK_PATHS:
        try:
            ip = await _query_local_api(sock_path)
            if ip:
                return ip
        except Exception as exc:
            logger.debug("Tailscale local API at %s unavailable: %s", sock_path, exc)
    return None


async def _query_local_api(sock_path: str) -> str | None:
    """Send a status request to the Tailscale local API socket."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await loop.sock_connect(sock, sock_path)

        request = (
            b"GET /localapi/v0/status HTTP/1.0\r\n"
            b"Host: local-tailscaled.sock\r\n"
            b"\r\n"
        )
        await loop.sock_sendall(sock, request)

        response = b""
        while True:
            chunk = await loop.sock_recv(sock, 65536)
            if not chunk:
                break
            response += chunk

        # Parse HTTP response body (skip headers)
        body_start = response.find(b"\r\n\r\n")
        if body_start == -1:
            return None
        body = response[body_start + 4:]
        status = json.loads(body)

        # Extract first IPv4 from TailscaleIPs
        self_status = status.get("Self", {})
        tailscale_ips = self_status.get("TailscaleIPs", [])
        for ip in tailscale_ips:
            if "." in ip:  # IPv4
                logger.info("Detected Tailscale IP via local API: %s", ip)
                return ip
        return None
    finally:
        sock.close()


async def _detect_via_cli() -> str | None:
    """Fall back to ``tailscale ip -4`` CLI command."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tailscale", "ip", "-4",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0 and stdout:
            ip = stdout.decode().strip().split("\n")[0]
            logger.info("Detected Tailscale IP via CLI: %s", ip)
            return ip
        logger.debug("tailscale ip -4 failed: %s", stderr.decode().strip())
        return None
    except FileNotFoundError:
        logger.debug("tailscale CLI not found on PATH")
        return None
    except asyncio.TimeoutError:
        logger.debug("tailscale CLI timed out")
        return None


async def ensure_tailscale_up(auth_key: str) -> bool:
    """Bring Tailscale up with the given auth key if not already connected.

    Returns ``True`` if Tailscale is connected after this call.
    """
    # Check if already connected
    ip = await detect_tailscale_ip()
    if ip:
        return True

    if not auth_key:
        logger.warning("No Tailscale auth key provided and Tailscale is not connected")
        return False

    logger.info("Bringing Tailscale up with auth key...")
    try:
        proc = await asyncio.create_subprocess_exec(
            "tailscale", "up", f"--authkey={auth_key}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            logger.error("tailscale up failed: %s", stderr.decode().strip())
            return False

        # Verify we got an IP
        ip = await detect_tailscale_ip()
        return ip is not None
    except FileNotFoundError:
        logger.error("tailscale CLI not found — is Tailscale installed?")
        return False
    except asyncio.TimeoutError:
        logger.error("tailscale up timed out after 30s")
        return False
