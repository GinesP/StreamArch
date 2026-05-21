"""Tests for QueuePlanner — thread-safe priority queues per band."""

import threading

import pytest

from app.domain.shared.types import QueueBand
from app.infrastructure.scheduler.queue_planner import QueuePlanner


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def planner() -> QueuePlanner:
    return QueuePlanner()


# ── Enqueue / Dequeue basics ─────────────────────────────────────────────


class TestEnqueueDequeue:
    def test_enqueue_and_dequeue_fast(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        item = planner.dequeue()
        assert item == ("s1", QueueBand.FAST)

    def test_enqueue_and_dequeue_medium(self, planner: QueuePlanner) -> None:
        planner.enqueue("s2", QueueBand.MEDIUM, "tiktok")
        item = planner.dequeue()
        assert item == ("s2", QueueBand.MEDIUM)

    def test_enqueue_and_dequeue_slow(self, planner: QueuePlanner) -> None:
        planner.enqueue("s3", QueueBand.SLOW, "youtube")
        item = planner.dequeue()
        assert item == ("s3", QueueBand.SLOW)

    def test_dequeue_returns_none_when_empty(self, planner: QueuePlanner) -> None:
        assert planner.dequeue() is None


class TestPriorityOrdering:
    def test_fast_before_medium(self, planner: QueuePlanner) -> None:
        planner.enqueue("slow", QueueBand.SLOW, "twitch")
        planner.enqueue("fast", QueueBand.FAST, "twitch")
        planner.enqueue("medium", QueueBand.MEDIUM, "twitch")

        sid, band = planner.dequeue()
        assert sid == "fast"
        assert band == QueueBand.FAST

    def test_fast_before_slow(self, planner: QueuePlanner) -> None:
        planner.enqueue("slow", QueueBand.SLOW, "twitch")
        planner.enqueue("fast", QueueBand.FAST, "twitch")

        sid, band = planner.dequeue()
        assert sid == "fast"
        assert band == QueueBand.FAST

    def test_medium_before_slow(self, planner: QueuePlanner) -> None:
        planner.enqueue("slow", QueueBand.SLOW, "twitch")
        planner.enqueue("medium", QueueBand.MEDIUM, "twitch")

        sid, band = planner.dequeue()
        assert sid == "medium"
        assert band == QueueBand.MEDIUM

    def test_fifo_within_same_band(self, planner: QueuePlanner) -> None:
        planner.enqueue("first", QueueBand.FAST, "twitch")
        planner.enqueue("second", QueueBand.FAST, "twitch")

        sid1, _ = planner.dequeue()
        sid2, _ = planner.dequeue()
        assert sid1 == "first"
        assert sid2 == "second"

    def test_all_queues_empty_returns_none(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        planner.dequeue()
        assert planner.dequeue() is None


class TestDequeueForBand:
    def test_dequeue_for_band_returns_platform(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "tiktok")
        item = planner.dequeue_for_band(QueueBand.FAST)
        assert item == ("s1", "tiktok")

    def test_dequeue_for_band_wrong_band(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        assert planner.dequeue_for_band(QueueBand.SLOW) is None

    def test_dequeue_for_band_empty(self, planner: QueuePlanner) -> None:
        assert planner.dequeue_for_band(QueueBand.FAST) is None

    def test_dequeue_for_band_fifo(self, planner: QueuePlanner) -> None:
        planner.enqueue("first", QueueBand.MEDIUM, "twitch")
        planner.enqueue("second", QueueBand.MEDIUM, "twitch")

        sid1, plat1 = planner.dequeue_for_band(QueueBand.MEDIUM)
        sid2, plat2 = planner.dequeue_for_band(QueueBand.MEDIUM)
        assert sid1 == "first"
        assert sid2 == "second"
        assert plat1 == "twitch"
        assert plat2 == "twitch"


# ── Introspection ────────────────────────────────────────────────────────


class TestQueueDepth:
    def test_queue_depth_starts_zero(self, planner: QueuePlanner) -> None:
        assert planner.queue_depth(QueueBand.FAST) == 0
        assert planner.queue_depth(QueueBand.MEDIUM) == 0
        assert planner.queue_depth(QueueBand.SLOW) == 0

    def test_queue_depth_after_enqueue(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        assert planner.queue_depth(QueueBand.FAST) == 1
        assert planner.queue_depth(QueueBand.MEDIUM) == 0

    def test_queue_depth_after_dequeue(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        planner.dequeue()
        assert planner.queue_depth(QueueBand.FAST) == 0

    def test_total_pending(self, planner: QueuePlanner) -> None:
        assert planner.total_pending() == 0
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        planner.enqueue("s2", QueueBand.MEDIUM, "twitch")
        planner.enqueue("s3", QueueBand.SLOW, "twitch")
        assert planner.total_pending() == 3


class TestClear:
    def test_clear_empties_all_queues(self, planner: QueuePlanner) -> None:
        planner.enqueue("s1", QueueBand.FAST, "twitch")
        planner.enqueue("s2", QueueBand.MEDIUM, "twitch")
        planner.enqueue("s3", QueueBand.SLOW, "twitch")
        planner.clear()
        assert planner.total_pending() == 0
        assert planner.dequeue() is None

    def test_clear_empty_is_safe(self, planner: QueuePlanner) -> None:
        planner.clear()  # Should not raise


# ── Thread safety ────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_enqueue_dequeue(self, planner: QueuePlanner) -> None:
        """Multiple threads can enqueue and dequeue without corruption."""
        n = 100
        results: list[str] = []
        results_lock = threading.Lock()

        def producer(start: int) -> None:
            for i in range(start, start + n):
                planner.enqueue(f"s{i}", QueueBand.FAST, "twitch")

        def consumer() -> None:
            seen = 0
            while seen < n * 2:  # 2 producers × 100
                item = planner.dequeue()
                if item is not None:
                    with results_lock:
                        results.append(item[0])
                    seen += 1
                else:
                    # Brief pause to avoid busy-spin on empty queue.
                    import time
                    time.sleep(0.001)

        producers = [
            threading.Thread(target=producer, args=(0,), daemon=True),
            threading.Thread(target=producer, args=(n,), daemon=True),
        ]
        consumers = [
            threading.Thread(target=consumer, daemon=True),
            threading.Thread(target=consumer, daemon=True),
        ]

        for t in producers + consumers:
            t.start()
        for t in producers:
            t.join(timeout=5.0)
        for t in consumers:
            t.join(timeout=5.0)

        assert len(results) == n * 2
        assert len(set(results)) == n * 2  # no duplicates
