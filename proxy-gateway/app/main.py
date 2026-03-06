import asyncio
import logging
import signal

import httpx
import uvicorn

from app.auth import AuthValidator
from app.config import settings
from app.logger import RequestLogger
from app.management import management_app
from app.proxy import ProxyServer
from app.socks5 import Socks5Server
from app.rate_limiter import RateLimiter
from app.routing import NodeRouter

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown_event.set)

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        # Initialize components
        auth_validator = AuthValidator(http_client, settings)
        node_router = NodeRouter(http_client, settings)
        rate_limiter = RateLimiter()
        request_logger = RequestLogger(http_client, settings)

        # Start background tasks
        await rate_limiter.start()
        await request_logger.start()

        # Start proxy server
        proxy = ProxyServer(
            auth_validator=auth_validator,
            node_router=node_router,
            rate_limiter=rate_limiter,
            request_logger=request_logger,
            settings=settings,
        )
        proxy_server = await proxy.start()

        # Start SOCKS5 server
        socks5 = Socks5Server(
            auth_validator=auth_validator,
            node_router=node_router,
            rate_limiter=rate_limiter,
            request_logger=request_logger,
            settings=settings,
        )
        socks5_server = await socks5.start()

        # Start management server
        uvicorn_config = uvicorn.Config(
            management_app,
            host="0.0.0.0",
            port=settings.MANAGEMENT_PORT,
            log_level=settings.LOG_LEVEL.lower(),
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)

        logger.info(
            "Space Router Proxy Gateway started — proxy:%d socks5:%d management:%d",
            settings.PROXY_PORT,
            settings.SOCKS5_PORT,
            settings.MANAGEMENT_PORT,
        )

        # Run until shutdown signal
        uvicorn_task = asyncio.create_task(uvicorn_server.serve())
        await shutdown_event.wait()

        # Graceful shutdown
        logger.info("Shutting down...")
        proxy_server.close()
        await proxy_server.wait_closed()
        socks5_server.close()
        await socks5_server.wait_closed()
        uvicorn_server.should_exit = True
        await uvicorn_task
        await rate_limiter.stop()
        await request_logger.stop()

    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
