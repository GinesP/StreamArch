"""QueuePlanner — thread-safe priority queues per queue band.

Provides three internal queues (FAST, MEDIUM, SLOW) and a priority-aware
``dequeue()`` that returns from FAST first, then MEDIUM, then SLOW —
preventing starvation of higher-priority targets.

Each queue item is a ``(stream_id, platform_key)`` tuple so that the
consumer (worker) can acquire the correct platform semaphore before
running the check.
"""

import queue
import threading

from app.domain.shared.types import QueueBand


class QueuePlanner:
    """Thread-safe priority-queue manager for monitoring checks.

    Typical usage::

        planner = QueuePlanner()
        planner.enqueue("stream-1", QueueBand.FAST, "twitch")
        planner.enqueue("stream-2", QueueBand.SLOW, "tiktok")

        item = planner.dequeue()          # ("stream-1", QueueBand.FAST)
        sid, plat = planner.dequeue_for_band(QueueBand.SLOW)  # ("stream-2", "tiktok")
    """

    def __init__(self) -> None:
        self._queues: dict[QueueBand, queue.Queue] = {
            QueueBand.FAST: queue.Queue(),
            QueueBand.MEDIUM: queue.Queue(),
            QueueBand.SLOW: queue.Queue(),
        }
        # Lock protects only multi-queue operations (dequeue priority scan).
        self._lock = threading.Lock()

    # ── Producers ─────────────────────────────────────────────────────

    def enqueue(
        self,
        stream_id: str,
        queue_band: QueueBand,
        platform_key: str,
    ) -> None:
        """Enqueue a stream target for a live check.

        Args:
            stream_id: Target identifier (e.g. ``StreamTarget.id``).
            queue_band: Priority band from ``get_queue_band()``.
            platform_key: Platform string (e.g. ``"twitch"``) that maps
                to a ``PlatformSemaphores`` gate.
        """
        self._queues[queue_band].put((stream_id, platform_key))

    # ── Consumers ─────────────────────────────────────────────────────

    def dequeue(self) -> tuple[str, QueueBand] | None:
        """Return the highest-priority pending item.

        Checks FAST → MEDIUM → SLOW in order.  Returns ``(stream_id, band)``
        or ``None`` when all queues are empty.
        """
        for band in (QueueBand.FAST, QueueBand.MEDIUM, QueueBand.SLOW):
            item = self._try_dequeue(band)
            if item is not None:
                stream_id, _ = item
                return (stream_id, band)
        return None

    def dequeue_for_band(self, band: QueueBand) -> tuple[str, str] | None:
        """Dequeue from a *specific* band only.

        Returns ``(stream_id, platform_key)`` or ``None`` if that band's
        queue is empty.  Used by the worker pool so that workers assigned
        to a band process only that band's items.
        """
        return self._try_dequeue(band)

    # ─── Introspection ────────────────────────────────────────────────

    def queue_depth(self, band: QueueBand) -> int:
        """Number of items pending in *band*'s queue."""
        return self._queues[band].qsize()

    def total_pending(self) -> int:
        """Total pending items across all bands."""
        return sum(q.qsize() for q in self._queues.values())

    def clear(self) -> None:
        """Remove all pending items from every queue."""
        for q in self._queues.values():
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    # ── Internal helpers ──────────────────────────────────────────────

    def _try_dequeue(self, band: QueueBand) -> tuple[str, str] | None:
        """Non-blocking dequeue from a single band (no lock needed).

        ``queue.Queue.get_nowait()`` is thread-safe on its own, so there's
        no need for the class-level lock in this helper.
        """
        try:
            return self._queues[band].get_nowait()
        except queue.Empty:
            return None
