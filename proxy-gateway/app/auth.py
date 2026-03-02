import base64
import hashlib
import logging
import time
from dataclasses import dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    valid: bool
    api_key_id: str | None = None
    rate_limit_rpm: int | None = None


def extract_api_key(headers: dict[str, str]) -> str | None:
    auth_value = headers.get("proxy-authorization") or headers.get("Proxy-Authorization")
    if not auth_value:
        return None

    parts = auth_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None

    try:
        decoded = base64.b64decode(parts[1]).decode("utf-8")
    except Exception:
        return None

    # Format is api_key: (key followed by colon, password is empty)
    api_key = decoded.split(":")[0]
    return api_key if api_key else None


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class AuthValidator:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings
        self._cache: dict[str, tuple[AuthResult, float]] = {}

    async def validate(self, api_key: str) -> AuthResult:
        key_hash = hash_api_key(api_key)
        now = time.monotonic()

        cached = self._cache.get(key_hash)
        if cached:
            result, cached_at = cached
            if now - cached_at < self._settings.AUTH_CACHE_TTL:
                return result

        try:
            resp = await self._client.post(
                f"{self._settings.COORDINATION_API_URL}/internal/auth/validate",
                json={"key_hash": key_hash},
                headers={"Authorization": f"Bearer {self._settings.COORDINATION_API_SECRET}"},
                timeout=5.0,
            )
        except httpx.HTTPError as e:
            logger.warning("Failed to validate API key: %s", e)
            return AuthResult(valid=False)

        if resp.status_code == 200:
            data = resp.json()
            result = AuthResult(
                valid=data.get("valid", False),
                api_key_id=data.get("api_key_id"),
                rate_limit_rpm=data.get("rate_limit_rpm"),
            )
            self._cache[key_hash] = (result, now)
            return result

        invalid = AuthResult(valid=False)
        # Cache invalid results for a shorter period
        self._cache[key_hash] = (invalid, now - self._settings.AUTH_CACHE_TTL + 60)
        return invalid
