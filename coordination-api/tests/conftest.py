import pytest
import respx

from app.config import Settings


@pytest.fixture
def settings():
    return Settings(
        PORT=8000,
        INTERNAL_API_SECRET="test-secret",
        SUPABASE_URL="http://supabase.test",
        SUPABASE_SERVICE_KEY="test-service-key",
        PROXYJET_HOST="proxy.proxyjet.io",
        PROXYJET_PORT=8080,
        PROXYJET_USERNAME="user123",
        PROXYJET_PASSWORD="pass456",
        PROXYJET_NODE_ID="00000000-0000-0000-0000-000000000001",
    )


@pytest.fixture
def mock_supabase():
    with respx.mock(assert_all_called=False) as mock:
        yield mock
