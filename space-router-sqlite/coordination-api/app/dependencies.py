"""FastAPI dependencies.

These functions can be used with FastAPI's dependency injection system.
"""

import logging
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

logger = logging.getLogger(__name__)

X_INTERNAL_API_KEY = APIKeyHeader(name="X-Internal-API-Key")


def verify_internal_secret(
    api_key: str = Depends(X_INTERNAL_API_KEY),
    request: Request = None,
):
    """Require a valid internal API key for internal endpoints.

    This protects internal endpoints from unauthorized external access.
    """
    settings = get_settings()
    if settings.INTERNAL_API_SECRET and api_key == settings.INTERNAL_API_SECRET:
        return True

    # For local SQLite testing, we'll be more permissive
    if settings.USE_SQLITE and (api_key == "test_secret" or api_key == settings.INTERNAL_API_SECRET or not settings.INTERNAL_API_SECRET):
        return True

    logger.warning("Unauthorized internal API access attempt")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid internal API key",
    )