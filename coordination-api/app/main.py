import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx

from app.config import get_settings
from app.db import SupabaseClient
from app.routers import api_keys, nodes, internal
from app.services.auth_service import AuthService
from app.services.ip_info_service import IPInfoService
from app.services.routing_service import RoutingService
from app.sqlite_db import SQLiteClient

logging.basicConfig(
    level=getattr(logging, get_settings().LOG_LEVEL.upper()),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Space Router Coordination API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers - these need to be included before startup_db_client
app.include_router(api_keys.router)
app.include_router(nodes.router)
app.include_router(internal.router)

@app.on_event("startup")
async def startup_db_client():
    settings = get_settings()
    logger.info(f"Coordination API starting on port {settings.PORT}")
    
    # Create an httpx client that will be passed to services
    http_client = httpx.AsyncClient()
    
    if settings.USE_SQLITE:
        # Use SQLite for local development
        app.state.db = SQLiteClient(settings.SQLITE_DB_PATH)
        logger.info(f"Using SQLite database at {settings.SQLITE_DB_PATH}")
    else:
        # Use Supabase (PostgREST) for production
        app.state.db = SupabaseClient(http_client, settings)
        logger.info("Using Supabase database")
    
    # Initialize services
    app.state.auth_service = AuthService(http_client, settings, app.state.db)
    app.state.ip_info_service = IPInfoService(http_client, settings.IPINFO_TOKEN)
    app.state.routing_service = RoutingService(http_client, settings, app.state.db)


@app.get("/healthz")
async def health_check():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readiness_check():
    """Readiness probe."""
    return {"status": "ok"}