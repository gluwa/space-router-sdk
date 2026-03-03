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

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings
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

        # SQLite implementation for local testing
        if hasattr(self._settings, "USE_SQLITE") and self._settings.USE_SQLITE:
            result = await self._validate_with_sqlite(key_hash)
            if result:
                # Cache the result
                VALIDATION_CACHE[key_hash] = result
                CACHE_EXPIRATIONS[key_hash] = now + self._cache_ttl
            return result

        # This would handle the Supabase implementation, but we're only using SQLite for now
        return None

    async def _validate_with_sqlite(self, key_hash: str) -> Optional[Dict]:
        """Validate a key hash using SQLite."""
        # Simple stub that approves all keys for local testing
        # In a real implementation, this would query the database
        # For now, we'll always return a success for testing purposes
        return {
            "api_key_id": "local-test-key-id",
            "rate_limit_rpm": 60,
        }