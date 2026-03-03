import asyncio
import time
from collections import deque
from math import ceil


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def check(self, api_key_id: str, rpm_limit: int) -> tuple[bool, int]:
        now = time.monotonic()
        window_start = now - 60.0

        async with self._lock:
            window = self._windows.get(api_key_id)
            if window is None:
                window = deque()
                self._windows[api_key_id] = window

            while window and window[0] < window_start:
                window.popleft()

            if len(window) >= rpm_limit:
                retry_after = ceil(60.0 - (now - window[0]))
                return False, max(retry_after, 1)

            window.append(now)
            return True, 0

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            window_start = now - 60.0
            async with self._lock:
                empty_keys = []
                for key, window in self._windows.items():
                    while window and window[0] < window_start:
                        window.popleft()
                    if not window:
                        empty_keys.append(key)
                for key in empty_keys:
                    del self._windows[key]
