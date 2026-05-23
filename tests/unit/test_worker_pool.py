"""Tests for WorkerPool — adaptive worker threads per queue band."""

import logging
import threading
from unittest.mock import MagicMock, call

import pytest

from app.domain.shared.types import QueueBand
from app.infrastructure.resolvers.result import ResolveResult
from app.infrastructure.scheduler.worker_pool import WorkerPool


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test")


@pytest.fixture
def queue_planner() -> MagicMock:
    m = MagicMock()
    # Workers call dequeue_for_band in a tight loop; default to None so
    # they don't crash trying to unpack a MagicMock tuple.
    m.dequeue_for_band.return_value = None
    return m


@pytest.fixture
def live_check_service() -> MagicMock:
    m = MagicMock()
    # Return a concrete ResolveResult so .is_live and .stream_url don't
    # generate nested MagicMocks that trip the new logging in worker_pool.
    m.check_stream.return_value = ResolveResult(
        is_live=False, stream_url=None,
    )
    return m


@pytest.fixture
def platform_semaphores() -> MagicMock:
    sem = MagicMock()
    # acquire_sync and release_sync are no-ops by default.
    return sem


@pytest.fixture
def pool(
    queue_planner: MagicMock,
    live_check_service: MagicMock,
    platform_semaphores: MagicMock,
    logger: logging.Logger,
) -> WorkerPool:
    return WorkerPool(
        queue_planner=queue_planner,
        live_check_service=live_check_service,
        platform_semaphores=platform_semaphores,
        logger=logger,
    )


# ── Lifecycle ────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_start_creates_base_workers(self, pool: WorkerPool) -> None:
        assert all(len(v) == 0 for v in pool._workers.values())
        pool.start()
        assert pool.worker_count == {
            QueueBand.FAST: 1,
            QueueBand.MEDIUM: 1,
            QueueBand.SLOW: 1,
        }
        pool.stop()

    def test_start_is_idempotent(self, pool: WorkerPool) -> None:
        pool.start()
        pool.start()  # Should not crash or create extra workers.
        assert pool.worker_count == {
            QueueBand.FAST: 1,
            QueueBand.MEDIUM: 1,
            QueueBand.SLOW: 1,
        }
        pool.stop()

    def test_stop_joins_workers(self, pool: WorkerPool) -> None:
        pool.start()
        assert pool.is_running
        pool.stop()
        # After stop, workers should have exited.
        assert not pool.is_running

    def test_monitor_thread_exists(self, pool: WorkerPool) -> None:
        pool.start()
        assert pool._monitor_thread is not None
        assert pool._monitor_thread.is_alive()
        pool.stop()
        assert not pool._monitor_thread.is_alive()


# ── Worker processing loop ───────────────────────────────────────────────


class TestWorkerProcessing:
    def test_worker_processes_dequeued_item(
        self,
        pool: WorkerPool,
        queue_planner: MagicMock,
        live_check_service: MagicMock,
        platform_semaphores: MagicMock,
    ) -> None:
        # Queue returns one item then None.
        queue_planner.dequeue_for_band.side_effect = [
            ("stream-1", "twitch"),
            None,
        ]
        pool.start()

        # Give the worker a moment to process.
        import time
        time.sleep(0.3)

        # Worker should have:
        #   1. dequeued from FAST
        #   2. acquired semaphore for "twitch"
        #   3. called check_stream("stream-1")
        #   4. released semaphore
        platform_semaphores.acquire_sync.assert_called_with("twitch")
        live_check_service.check_stream.assert_called_with("stream-1")
        platform_semaphores.release_sync.assert_called_with("twitch")

        pool.stop()

    def test_worker_handles_check_error(
        self,
        pool: WorkerPool,
        queue_planner: MagicMock,
        live_check_service: MagicMock,
        platform_semaphores: MagicMock,
    ) -> None:
        """Worker should not crash when check_stream raises."""
        live_check_service.check_stream.side_effect = ValueError("boom")
        queue_planner.dequeue_for_band.side_effect = [
            ("stream-1", "twitch"),
            None,
        ]
        pool.start()

        import time
        time.sleep(0.3)

        # Semaphore should still be released despite the error.
        platform_semaphores.release_sync.assert_called_with("twitch")
        pool.stop()

    def test_worker_loops_until_stop(
        self,
        pool: WorkerPool,
        queue_planner: MagicMock,
    ) -> None:
        """Worker should keep polling until stopped."""
        queue_planner.dequeue_for_band.return_value = None
        pool.start()

        # Give the worker time to poll a few times.
        import time
        time.sleep(0.5)

        # Should have polled multiple times.
        assert queue_planner.dequeue_for_band.call_count >= 2

        pool.stop()

    def test_worker_processes_multiple_items(
        self,
        pool: WorkerPool,
        queue_planner: MagicMock,
        live_check_service: MagicMock,
    ) -> None:
        """Worker handles back-to-back items."""
        queue_planner.dequeue_for_band.side_effect = [
            ("s1", "twitch"),
            ("s2", "twitch"),
            ("s3", "twitch"),
            None,
        ]
        pool.start()

        import time
        time.sleep(0.5)

        assert live_check_service.check_stream.call_count == 3
        live_check_service.check_stream.assert_has_calls([
            call("s1"),
            call("s2"),
            call("s3"),
        ])
        pool.stop()


# ── Worker allocation / boost ────────────────────────────────────────────


class TestAdjustWorkers:
    def test_base_allocation(self, pool: WorkerPool) -> None:
        """With no depth, no boost worker is added."""
        pool.adjust_workers(fast_depth=0, medium_depth=0, slow_depth=0)
        # No workers exist yet (start wasn't called, and adjust_workers
        # only manages the boost, not base workers).
        assert all(len(v) == 0 for v in pool._workers.values())

    def test_boost_adds_worker_to_congested_band(self, pool: WorkerPool) -> None:
        """Most-congested band gets an extra worker."""
        # Start with base workers.
        pool.start()
        base_counts = pool.worker_count
        assert base_counts[QueueBand.FAST] == 1

        # FAST has items — boost it.
        pool.adjust_workers(fast_depth=5, medium_depth=0, slow_depth=0)
        assert pool.worker_count[QueueBand.FAST] == 2
        assert pool.worker_count[QueueBand.MEDIUM] == 1
        assert pool.worker_count[QueueBand.SLOW] == 1
        pool.stop()

    def test_no_boost_when_all_empty(self, pool: WorkerPool) -> None:
        """No boost worker is added when no queues have items."""
        pool.start()
        pool.adjust_workers(fast_depth=0, medium_depth=0, slow_depth=0)
        assert all(v == 1 for v in pool.worker_count.values())
        pool.stop()

    def test_boost_prefers_most_congested(self, pool: WorkerPool) -> None:
        """Boost goes to the band with the deepest queue."""
        pool.start()
        pool.adjust_workers(fast_depth=1, medium_depth=10, slow_depth=0)
        assert pool.worker_count[QueueBand.FAST] == 1
        assert pool.worker_count[QueueBand.MEDIUM] == 2
        assert pool.worker_count[QueueBand.SLOW] == 1
        pool.stop()

    def test_no_boost_when_band_already_at_max(self, pool: WorkerPool) -> None:
        """If the congested band already has 2 workers, no more."""
        pool.start()
        # Manually add a second worker to FAST.
        pool._add_worker(QueueBand.FAST)
        pool.adjust_workers(fast_depth=10, medium_depth=0, slow_depth=0)
        # FAST already has 2 (1 base + 1 manual) — no 3rd.
        assert pool.worker_count[QueueBand.FAST] == 2
        pool.stop()

    def test_max_total_workers_not_exceeded(self, pool: WorkerPool) -> None:
        """Total workers never exceeds MAX_TOTAL (4)."""
        pool.start()  # 3 base workers

        # Try to add boost to each band sequentially (simulate congestion shifts).
        pool.adjust_workers(fast_depth=10, medium_depth=0, slow_depth=0)
        total = sum(pool.worker_count.values())
        assert total <= 4
        pool.stop()


# ── Integration-style: Monitor calls adjust_workers ──────────────────────


class TestMonitorLoop:
    def test_monitor_checks_depths_and_adjusts(
        self,
        pool: WorkerPool,
        queue_planner: MagicMock,
    ) -> None:
        """Monitor thread reads depths and calls adjust_workers."""
        queue_planner.queue_depth.side_effect = lambda band: {
            QueueBand.FAST: 5,
            QueueBand.MEDIUM: 0,
            QueueBand.SLOW: 0,
        }.get(band, 0)

        # Reduce monitor interval so the test doesn't wait 15s.
        pool._MONITOR_INTERVAL = 0.1
        pool.start()
        import time
        time.sleep(0.5)

        # Should have called queue_depth for each band at least once.
        assert queue_planner.queue_depth.call_count >= 3

        pool.stop()
