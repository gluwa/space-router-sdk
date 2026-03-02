import asyncio
import logging
from dataclasses import asdict, dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
FLUSH_INTERVAL = 1.0


@dataclass
class RequestLog:
    request_id: str
    api_key_id: str
    node_id: str | None
    method: str
    target_host: str
    status_code: int | None
    bytes_sent: int
    bytes_received: int
    latency_ms: int
    success: bool
    error_type: str | None
    created_at: str  # ISO 8601


class RequestLogger:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10000)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._consumer())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            # Flush remaining
            await self._flush_all()

    def log(self, entry: RequestLog) -> None:
        try:
            self._queue.put_nowait(asdict(entry))
        except asyncio.QueueFull:
            logger.warning("Request log queue full, dropping entry")

    async def _consumer(self) -> None:
        while True:
            batch: list[dict] = []
            try:
                # Wait for first item
                item = await asyncio.wait_for(self._queue.get(), timeout=FLUSH_INTERVAL)
                batch.append(item)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return

            # Drain up to BATCH_SIZE
            while len(batch) < BATCH_SIZE:
                try:
                    item = self._queue.get_nowait()
                    batch.append(item)
                except asyncio.QueueEmpty:
                    break

            await self._insert_batch(batch)

    async def _flush_all(self) -> None:
        batch: list[dict] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._insert_batch(batch)

    async def _insert_batch(self, batch: list[dict]) -> None:
        if not self._settings.SUPABASE_URL or not self._settings.SUPABASE_SERVICE_KEY:
            logger.debug("Supabase not configured, skipping log insert (%d entries)", len(batch))
            return

        try:
            await self._client.post(
                f"{self._settings.SUPABASE_URL}/rest/v1/request_logs",
                json=batch,
                headers={
                    "apikey": self._settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {self._settings.SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                timeout=10.0,
            )
        except Exception as e:
            logger.error("Failed to insert request logs batch (%d entries): %s", len(batch), e)
