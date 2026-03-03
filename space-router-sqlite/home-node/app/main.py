"""Home Node Daemon — entry point.

Lifecycle:
  1. Detect public IP (or use configured value)
  2. Register with Coordination API
  3. Start asyncio TCP server
  4. Wait for SIGTERM / SIGINT
  5. Deregister node (best-effort)
  6. Shutdown
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
        # 1. Detect public IP
        if s.PUBLIC_IP:
            public_ip = s.PUBLIC_IP
            logger.info("Using configured public IP: %s", public_ip)
        else:
            try:
                public_ip = await detect_public_ip(http_client)
            except RuntimeError:
                logger.error("Cannot detect public IP — aborting")
                sys.exit(1)

        # 2. Register with Coordination API
        try:
            node_id = await register_node(http_client, s, public_ip)
        except Exception:
            logger.exception("Failed to register with Coordination API — aborting")
            sys.exit(1)

        # 3. Start TCP server
        handler = functools.partial(handle_client, settings=s)
        server = await asyncio.start_server(handler, host="0.0.0.0", port=s.NODE_PORT)
        logger.info("Home Node listening on port %d (node_id=%s)", s.NODE_PORT, node_id)

        try:
            await stop_event.wait()
        finally:
            logger.info("Shutting down…")

            # 4. Stop accepting new connections
            server.close()
            await server.wait_closed()

            # 5. Deregister (best-effort)
            await deregister_node(http_client, s, node_id)

    logger.info("Home Node shut down cleanly")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
