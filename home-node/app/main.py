"""Home Node Daemon — entry point.

Lifecycle:
  1. Detect Tailscale IP (if enabled)
  2. Detect public IP (or use configured value)
  3. Register with Coordination API
  4. Start asyncio TCP server
  5. Wait for SIGTERM / SIGINT
  6. Deregister node (best-effort)
  7. Shutdown
"""

import asyncio
import functools
import logging
import signal
import sys

import httpx

from app.config import settings
from app.proxy_handler import handle_client
from app.registration import deregister_node, detect_public_ip, register_node

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _run(settings_override=None) -> None:  # noqa: ANN001
    s = settings_override or settings
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    async with httpx.AsyncClient() as http_client:
        # 1. Detect Tailscale IP (if enabled)
        tailscale_ip = None
        if s.TAILSCALE_ENABLED:
            from app.tailscale import detect_tailscale_ip, ensure_tailscale_up

            if s.TAILSCALE_AUTH_KEY:
                await ensure_tailscale_up(s.TAILSCALE_AUTH_KEY)

            tailscale_ip = await detect_tailscale_ip()
            if tailscale_ip:
                logger.info("Tailscale IP: %s", tailscale_ip)
            else:
                logger.warning(
                    "Tailscale enabled but no IP detected — "
                    "falling back to direct public IP mode"
                )

        # 2. Detect public IP (always needed for metadata)
        if s.PUBLIC_IP:
            public_ip = s.PUBLIC_IP
            logger.info("Using configured public IP: %s", public_ip)
        else:
            try:
                public_ip = await detect_public_ip(http_client)
            except RuntimeError:
                logger.error("Cannot detect public IP — aborting")
                sys.exit(1)

        # 3. Register with Coordination API
        try:
            node_id = await register_node(
                http_client, s, public_ip, tailscale_ip=tailscale_ip,
            )
        except Exception:
            logger.exception("Failed to register with Coordination API — aborting")
            sys.exit(1)

        # 4. Start TCP server
        handler = functools.partial(handle_client, settings=s)
        server = await asyncio.start_server(handler, host="0.0.0.0", port=s.NODE_PORT)
        logger.info(
            "Home Node listening on port %d (node_id=%s, tailscale=%s)",
            s.NODE_PORT, node_id, tailscale_ip or "disabled",
        )

        try:
            await stop_event.wait()
        finally:
            logger.info("Shutting down…")

            # 5. Stop accepting new connections
            server.close()
            await server.wait_closed()

            # 6. Deregister (best-effort)
            await deregister_node(http_client, s, node_id)

    logger.info("Home Node shut down cleanly")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
