"""Authentication service for validating API keys."""

import logging
import time
from typing import Dict, Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Simple in-memory cache for auth validation results
VALIDATION_CACHE: Dict[str, Dict] = {}
CACHE_EXPIRATIONS: Dict[str, float] = {}


class AuthService:
    """Authenticates API key requests."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings, *, db=None) -> None:
        self._client = http_client
        self._settings = settings
        self._db = db
        self._cache_ttl = 300  # 5 minutes

    async def validate_key_hash(self, key_hash: str) -> Optional[Dict]:
        """Validate a key hash against the database."""
        # Check cache first
        now = time.time()
        if key_hash in VALIDATION_CACHE:
            if CACHE_EXPIRATIONS.get(key_hash, 0) > now:
                return VALIDATION_CACHE[key_hash]
            # Expired, clean up cache
            del VALIDATION_CACHE[key_hash]
            del CACHE_EXPIRATIONS[key_hash]

        if self._db is None:
            logger.error("No database client configured for auth validation")
            return None

        result = await self._validate_with_db(key_hash)
        if result:
            # Cache the result
            VALIDATION_CACHE[key_hash] = result
            CACHE_EXPIRATIONS[key_hash] = now + self._cache_ttl
        return result

    async def _validate_with_db(self, key_hash: str) -> Optional[Dict]:
        """Validate a key hash by querying the api_keys table."""
        try:
            row = await self._db.select(
                "api_keys",
                params={"key_hash": key_hash, "is_active": "1"},
                single=True,
            )
            if row is None:
                logger.info("API key hash not found or inactive")
                return None
            return {
                "api_key_id": row["id"],
                "rate_limit_rpm": row.get("rate_limit_rpm", 60),
            }
        except Exception as e:
            logger.error("Failed to validate key hash: %s", e)
            return None
