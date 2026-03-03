import pytest

from app.config import Settings


@pytest.fixture
def settings():
    return Settings(
        NODE_PORT=0,  # OS picks a free port
        COORDINATION_API_URL="http://localhost:8000",
        NODE_LABEL="test-node",
        NODE_REGION="us-west",
        NODE_TYPE="residential",
        PUBLIC_IP="127.0.0.1",
        BUFFER_SIZE=65536,
        REQUEST_TIMEOUT=5.0,
        RELAY_TIMEOUT=10.0,
        LOG_LEVEL="DEBUG",
    )
