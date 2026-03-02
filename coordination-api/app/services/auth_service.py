import logging

from app.db import SupabaseClient

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    async def validate_key_hash(self, key_hash: str) -> dict | None:
        """Look up an API key by its SHA-256 hash.

        Returns {"api_key_id": str, "rate_limit_rpm": int} if valid, else None.
        """
        try:
            row = await self._db.select(
                "api_keys",
                params={
                    "key_hash": f"eq.{key_hash}",
                    "is_active": "eq.true",
                    "select": "id,rate_limit_rpm",
                },
                single=True,
            )
        except Exception:
            logger.exception("Failed to validate key hash")
            return None

        if row is None:
            return None

        return {
            "api_key_id": row["id"],
            "rate_limit_rpm": row.get("rate_limit_rpm") or 60,
        }
