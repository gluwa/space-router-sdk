"""Authentication for proxy requests.

Handles extracting and validating API keys from Proxy-Authorization headers.
"""

import base64
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

from app.config import Settings
from app.errors import AuthenticationError

logger = logging.getLogger(__name__)

# In-memory cache for auth validation
VALIDATION_CACHE: Dict[str, Dict] = {}
VALIDATION_EXPIRATIONS: Dict[str, float] = {}


@dataclass
class AuthResult:
    api_key_id: str
    rate_limit_rpm: int
    valid: bool = True  # Default to True for the local SQLite implementation


def extract_api_key(auth_header: str | None) -> str:
    """Extract API key from Proxy-Authorization header."""
    if not auth_header:
        raise AuthenticationError("Missing Proxy-Authorization header")

    # Expect: "Basic BASE64(api_key:)" or "Basic BASE64(api_key)"
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "basic":
        raise AuthenticationError("Invalid authentication type, expected Basic")

    try:
        decoded = base64.b64decode(parts[1]).decode("utf-8")
        # The API key may be passed as either "api_key:" or just "api_key"
        # We want to handle both cases
        key = decoded.split(":", 1)[0]
        if not key:
            raise AuthenticationError("Empty API key")
        return key
    except (ValueError, UnicodeDecodeError):
        raise AuthenticationError("Malformed authentication header")


def hash_api_key(api_key: str) -> str:
    """Compute SHA-256 hash of API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class AuthValidator:
    """Validates API keys against the Coordination API."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings
        self._cache_ttl = getattr(settings, "AUTH_CACHE_TTL", 300)  # 5 minutes

    async def validate(self, api_key: str) -> Optional[AuthResult]:
        """Validate an API key and return auth result if valid."""
        # Get key hash
        key_hash = hash_api_key(api_key)

        # Check if we have a cached result
        now = time.time()
        if key_hash in VALIDATION_CACHE:
            if VALIDATION_EXPIRATIONS.get(key_hash, 0) > now:
                result = VALIDATION_CACHE[key_hash]
                return AuthResult(
                    api_key_id=result["api_key_id"],
                    rate_limit_rpm=result["rate_limit_rpm"],
                )
            # Expired, clean up cache
            del VALIDATION_CACHE[key_hash]
            del VALIDATION_EXPIRATIONS[key_hash]

        # Validate with Coordination API
        try:
            headers = {"X-Internal-API-Key": self._settings.COORDINATION_API_SECRET}
            
            response = await self._client.post(
                f"{self._settings.COORDINATION_API_URL}/internal/auth/validate",
                json={"key_hash": key_hash},
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            result = response.json()

            if not result["valid"]:
                return None

            # Cache the result
            VALIDATION_CACHE[key_hash] = {
                "api_key_id": result["api_key_id"],
                "rate_limit_rpm": result["rate_limit_rpm"],
            }
            VALIDATION_EXPIRATIONS[key_hash] = now + self._cache_ttl

            return AuthResult(
                api_key_id=result["api_key_id"],
                rate_limit_rpm=result["rate_limit_rpm"],
            )
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("Auth validation failed: %s", e)
            # For SQLite testing, we'll allow requests to go through
            if hasattr(self._settings, "USE_SQLITE") and self._settings.USE_SQLITE:
                logger.info("Using local test key for SQLite testing")
                return AuthResult(api_key_id="local-test-key", rate_limit_rpm=60)
            return None