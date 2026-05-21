"""Tests for PlatformSemaphores — per-platform concurrency gates."""

import threading
import time

import pytest

from app.infrastructure.scheduler.platform_semaphores import PlatformSemaphores


class TestPlatformSemaphoresInit:
    def test_default_limit(self) -> None:
        sem = PlatformSemaphores()
        assert sem._default_limit == 3

    def test_custom_limit(self) -> None:
        sem = PlatformSemaphores(default_limit=5)
        assert sem._default_limit == 5

    def test_invalid_limit_raises(self) -> None:
        with pytest.raises(ValueError):
            PlatformSemaphores(default_limit=0)


class TestPlatformSemaphoresSync:
    def test_acquire_release_single_platform(self) -> None:
        sem = PlatformSemaphores(default_limit=1)
        sem.acquire_sync("twitch")
        # Without release, a second acquire would block (we test via
        # timeout to avoid deadlock).
        sem.release_sync("twitch")
        # After release, we can acquire again.
        sem.acquire_sync("twitch")
        sem.release_sync("twitch")

    def test_concurrent_limit_is_enforced(self) -> None:
        """With limit=1, two acquires block until the first releases."""
        sem = PlatformSemaphores(default_limit=1)
        sem.acquire_sync("twitch")

        blocked = threading.Event()
        acquired = threading.Event()

        def try_acquire() -> None:
            blocked.set()
            sem.acquire_sync("twitch")
            acquired.set()
            sem.release_sync("twitch")

        t = threading.Thread(target=try_acquire, daemon=True)
        t.start()
        blocked.wait(timeout=0.5)

        # The second thread should be blocked (not yet acquired).
        assert not acquired.is_set()

        # Release the first slot — the second thread should unblock.
        sem.release_sync("twitch")
        acquired.wait(timeout=1.0)
        assert acquired.is_set()
        t.join(timeout=1.0)

    def test_platforms_are_independent(self) -> None:
        """Limit for one platform does not affect another."""
        sem = PlatformSemaphores(default_limit=1)
        sem.acquire_sync("twitch")

        # Should be able to acquire for a different platform.
        sem.acquire_sync("tiktok")
        sem.release_sync("tiktok")
        sem.release_sync("twitch")

    def test_default_limit_allows_three(self) -> None:
        """With default limit 3, three acquires should all succeed."""
        sem = PlatformSemaphores(default_limit=3)
        sem.acquire_sync("twitch")
        sem.acquire_sync("twitch")
        sem.acquire_sync("twitch")
        # Fourth would block — we don't test that here.
        sem.release_sync("twitch")
        sem.release_sync("twitch")
        sem.release_sync("twitch")


class TestPlatformSemaphoresAsync:
    @pytest.mark.asyncio
    async def test_async_acquire(self) -> None:
        sem = PlatformSemaphores(default_limit=1)
        # Should complete without blocking forever.
        await sem.acquire("twitch")
        sem.release("twitch")

    @pytest.mark.asyncio
    async def test_release_is_sync_alias(self) -> None:
        sem = PlatformSemaphores(default_limit=1)
        await sem.acquire("twitch")
        sem.release("twitch")  # sync call

    def test_release_sync_matches_sync(self) -> None:
        sem = PlatformSemaphores(default_limit=1)
        sem.acquire_sync("twitch")
        sem.release_sync("twitch")
        sem.acquire_sync("twitch")
        sem.release_sync("twitch")


class TestPlatformSemaphoresEdgeCases:
    def test_lazy_semaphore_creation(self) -> None:
        """Semaphore is created on first access, not at init."""
        sem = PlatformSemaphores()
        assert "unknown_platform" not in sem._semaphores
        sem.acquire_sync("unknown_platform")
        assert "unknown_platform" in sem._semaphores
        sem.release_sync("unknown_platform")

    def test_thread_safety(self) -> None:
        """Multiple threads should be able to acquire/release safely."""
        sem = PlatformSemaphores(default_limit=2)
        results: list[int] = []
        results_lock = threading.Lock()

        def worker(worker_id: int) -> None:
            for _ in range(10):
                sem.acquire_sync("twitch")
                with results_lock:
                    results.append(worker_id)
                sem.release_sync("twitch")

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert len(results) == 40  # 4 workers × 10 acquisitions
