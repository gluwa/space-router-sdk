import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import settings
from app.db import SupabaseClient
from app.routers import api_keys, internal, nodes
from app.services.auth_service import AuthService
from app.services.routing_service import RoutingService

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    http_client = httpx.AsyncClient()
    db = SupabaseClient(http_client, settings)

    app.state.settings = settings
    app.state.http_client = http_client
    app.state.db = db
    app.state.auth_service = AuthService(db)
    app.state.routing_service = RoutingService(db, settings)

    logger.info("Coordination API starting on port %d", settings.PORT)
    yield

    await http_client.aclose()
    logger.info("Coordination API shut down")


app = FastAPI(title="Space Router Coordination API", lifespan=lifespan)

app.include_router(internal.router)
app.include_router(api_keys.router)
app.include_router(nodes.router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "healthy"}


@app.get("/readyz")
async def readyz() -> dict:
    # Could check DB connectivity here
    return {"status": "ready"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
