import asyncio

import httpx
import pytest
import respx

from app.auth import AuthValidator
from app.config import Settings
from app.logger import RequestLogger
from app.rate_limiter import RateLimiter
from app.routing import NodeRouter


@pytest.fixture
def settings():
    return Settings(
        PROXY_PORT=0,  # OS-assigned port for tests
        MANAGEMENT_PORT=0,
        COORDINATION_API_URL="http://coordination.test",
        COORDINATION_API_SECRET="test-secret",
        SUPABASE_URL="",
        SUPABASE_SERVICE_KEY="",
        DEFAULT_RATE_LIMIT_RPM=60,
        NODE_REQUEST_TIMEOUT=5.0,
        AUTH_CACHE_TTL=300,
        BUFFER_SIZE=65536,
        LOG_LEVEL="DEBUG",
    )


@pytest.fixture
def http_client():
    return httpx.AsyncClient()


@pytest.fixture
def auth_validator(http_client, settings):
    return AuthValidator(http_client, settings)


@pytest.fixture
def node_router(http_client, settings):
    return NodeRouter(http_client, settings)


@pytest.fixture
def rate_limiter():
    return RateLimiter()


@pytest.fixture
def request_logger(http_client, settings):
    return RequestLogger(http_client, settings)


@pytest.fixture
def mock_api():
    with respx.mock(assert_all_called=False) as mock:
        yield mock
