"""PlatformSemaphores — per-platform concurrency limits.

Prevents hitting rate limits by limiting how many concurrent checks
or recordings can run per platform.

Uses ``threading.Semaphore`` internally — one semaphore per platform
key — with a configurable default limit.
"""

import asyncio
import threading


class PlatformSemaphores:
    """Per-platform concurrency gates.

    Usage (threaded workers)::

        sem = PlatformSemaphores(default_limit=3)
        sem.acquire_sync("twitch")
        try:
            # … do the check …
        finally:
            sem.release_sync("twitch")
    """

    def __init__(self, default_limit: int = 3) -> None:
        if default_limit < 1:
            raise ValueError("default_limit must be >= 1")
        self._default_limit = default_limit
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    # ── Async API (for future use with async workers) ─────────────────

    async def acquire(self, platform_key: str) -> None:
        """Acquire the semaphore for *platform_key* (async).

        Runs the blocking acquire in a thread-pool executor.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.acquire_sync, platform_key)

    def release(self, platform_key: str) -> None:
        """Release the semaphore for *platform_key* (sync alias)."""
        self.release_sync(platform_key)

    # ── Sync API (for threaded workers) ───────────────────────────────

    def acquire_sync(self, platform_key: str) -> None:
        """Acquire the semaphore for *platform_key* (blocking).

        Blocks until a slot becomes available for this platform.
        """
        sem = self._get_or_create(platform_key)
        sem.acquire()

    def release_sync(self, platform_key: str) -> None:
        """Release the semaphore for *platform_key*."""
        sem = self._get_or_create(platform_key)
        sem.release()

    # ── Internals ─────────────────────────────────────────────────────

    def _get_or_create(self, platform_key: str) -> threading.Semaphore:
        """Return the semaphore for *platform_key*, creating if absent."""
        # Fast path: already exists  (read-only, no lock needed for dict
        # lookup if we assume the typical case, but dict is mutable so
        # we lock to be safe).
        with self._lock:
            if platform_key not in self._semaphores:
                self._semaphores[platform_key] = threading.Semaphore(
                    self._default_limit
                )
            return self._semaphores[platform_key]
