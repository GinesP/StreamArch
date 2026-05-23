"""WorkerPool — manages adaptive workers per queue band.

Workers are daemon threads that dequeue items from a ``QueuePlanner``,
acquire the correct platform semaphore, run the live check, then release
the semaphore.

Worker allocation
-----------------
* **Base**: 1 worker per queue band (3 total) — always alive.
* **Boost**: a mobile 4th worker that can be:
  - **Added** (scale-up) when a queue exceeds its threshold
  - **Moved** (reassign) when another queue is 2× more congested
  - **Removed** (scale-down) when the boosted queue is empty for 60 s
* **Only one band** may hold the boost at any time.
* **Max per band**: 2 workers.
* **Total max**: 4 workers (3 base + 1 boost).
* A monitor thread checks queue depths every 15 seconds and decides
  scale-up, reassign, or scale-down.
"""

import logging
import random
import threading
import time
from collections.abc import Callable

from app.domain.shared.types import QueueBand


class WorkerPool:
    """Adaptive threaded worker pool for queue-based live checks.

    Parameters
    ----------
    queue_planner:
        Shared ``QueuePlanner`` instance (populated by ``MonitoringCycle``).
    live_check_service:
        Application service that runs the resolver chain and persists
        check results.  Called from worker threads.
    platform_semaphores:
        Per-platform concurrency gates (``PlatformSemaphores``).
    logger:
        Optional logger; falls back to a module-level logger.
    """

    #: Maximum worker threads per queue band.
    _MAX_PER_BAND: int = 2
    #: Maximum total worker threads across all bands.
    _MAX_TOTAL: int = 4
    #: Base worker count per band (1 = always-on).
    _BASE_PER_BAND: int = 1
    #: Seconds between worker-allocation monitor checks.
    _MONITOR_INTERVAL: float = 15.0
    #: Queue depth thresholds that trigger a scale-up per band.
    _SCALE_UP_THRESHOLDS: dict[str, int] = {
        "fast": 5,
        "medium": 8,
        "slow": 5,
    }
    #: Seconds a queue must be empty before the boost is removed.
    _SCALE_DOWN_IDLE_SECONDS: float = 60.0

    def __init__(
        self,
        queue_planner,
        live_check_service,
        platform_semaphores,
        result_store=None,
        logger: logging.Logger | None = None,
        due_checker: Callable[[str], bool] | None = None,
    ) -> None:
        self._queue_planner = queue_planner
        self._live_check_service = live_check_service
        self._semaphores = platform_semaphores
        self._result_store = result_store
        self._logger = logger or logging.getLogger(__name__)
        self._due_checker = due_checker

        # ── Internal state ────────────────────────────────────────────
        self._stop_event = threading.Event()
        self._workers: dict[QueueBand, list[threading.Thread]] = {
            QueueBand.FAST: [],
            QueueBand.MEDIUM: [],
            QueueBand.SLOW: [],
        }
        self._monitor_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # ── Adaptive boost tracking ───────────────────────────────────
        self._boost_band: QueueBand | None = None
        self._boost_empty_since: float | None = None
        self._workers_to_stop: dict[QueueBand, int] = {
            QueueBand.FAST: 0,
            QueueBand.MEDIUM: 0,
            QueueBand.SLOW: 0,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start base workers (1 per band) and the allocation monitor.

        Idempotent — subsequent calls are no-ops when already running.
        """
        if self.is_running:
            self._logger.warning("WorkerPool is already running")
            return

        self._stop_event.clear()
        for band in QueueBand:
            for _ in range(self._BASE_PER_BAND):
                self._add_worker(band)

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="worker-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

        self._logger.info(
            "WorkerPool started (%d base workers)",
            self._BASE_PER_BAND * len(QueueBand),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal all workers to stop and wait for them to finish.

        Args:
            timeout: Maximum seconds to wait per thread.
        """
        self._stop_event.set()
        deadline = time.monotonic() + timeout

        all_threads = [
            t for threads in self._workers.values() for t in threads
        ]
        for t in all_threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if t.is_alive():
                t.join(timeout=remaining)

        self._logger.info("WorkerPool stopped")

    @property
    def is_running(self) -> bool:
        """Whether any worker thread is alive."""
        return any(
            t.is_alive() for threads in self._workers.values() for t in threads
        )

    @property
    def worker_count(self) -> dict[QueueBand, int]:
        """Current worker count per band."""
        return {band: len(threads) for band, threads in self._workers.items()}

    @property
    def due_checker(self) -> Callable[[str], bool] | None:
        """Optional callable to validate whether a dequeued stream is still due."""
        return self._due_checker

    @due_checker.setter
    def due_checker(self, value: Callable[[str], bool] | None) -> None:
        self._due_checker = value

    # ── Allocation policy ─────────────────────────────────────────────

    def adjust_workers(
        self,
        fast_depth: int,
        medium_depth: int,
        slow_depth: int,
    ) -> None:
        """Evaluate queue depths and adjust boost worker allocation.

        Called periodically by the internal monitor thread.

        Policy (recoded per scheduler-redesign-v2.md):
        * Base workers (1 per band) are always alive.
        * At most **one band** may hold the boost (2 workers).
        * **Scale-up**: add boost to a band that exceeds its threshold
          when no other band has the boost.
        * **Reassign**: move boost when another band is 2× more congested.
        * **Scale-down**: remove boost when the boosted band has been
          empty for ``_SCALE_DOWN_IDLE_SECONDS``.
        """
        depths: dict[QueueBand, int] = {
            QueueBand.FAST: fast_depth,
            QueueBand.MEDIUM: medium_depth,
            QueueBand.SLOW: slow_depth,
        }

        current = self.worker_count
        total_current = sum(current.values())
        has_pending = any(d > 0 for d in depths.values())

        # ── Determine which band (if any) currently holds the boost ──
        boost_band: QueueBand | None = None
        for band in QueueBand:
            if current[band] > self._BASE_PER_BAND:
                boost_band = band
                break

        # ── Scale-down: remove boost from idle band ──────────────────
        if boost_band is not None and depths[boost_band] == 0:
            now = time.monotonic()
            if self._boost_empty_since is None:
                self._boost_empty_since = now
            elif (now - self._boost_empty_since) >= self._SCALE_DOWN_IDLE_SECONDS:
                self._logger.info(
                    "Scale-down: removing boost from %s band (empty for %.0fs)",
                    boost_band.value, self._SCALE_DOWN_IDLE_SECONDS,
                )
                self._remove_worker(boost_band)
                self._boost_band = None
                self._boost_empty_since = None
            return

        # Reset empty timer if the boosted queue has items again.
        if boost_band is not None:
            self._boost_empty_since = None

        # ── Find the most congested band ─────────────────────────────
        max_depth_band = max(depths, key=depths.get)
        max_depth = depths[max_depth_band]

        # ── Reassign: move boost to a band 2× more congested ────────
        if boost_band is not None and max_depth_band != boost_band:
            if (max_depth >= 2 * depths[boost_band]
                    and max_depth >= self._SCALE_UP_THRESHOLDS[max_depth_band.value]
                    and current[max_depth_band] < self._MAX_PER_BAND):
                self._logger.info(
                    "Reassign: moving boost from %s to %s band "
                    "(depths: %s=%d, %s=%d)",
                    boost_band.value, max_depth_band.value,
                    boost_band.value, depths[boost_band],
                    max_depth_band.value, max_depth,
                )
                self._add_worker(max_depth_band)
                self._remove_worker(boost_band)
                self._boost_band = max_depth_band
                self._boost_empty_since = None
            return

        # ── Scale-up: add boost to a congested band ─────────────────
        if boost_band is None and has_pending and total_current < self._MAX_TOTAL:
            candidates = [
                b for b in QueueBand
                if depths[b] >= self._SCALE_UP_THRESHOLDS[b.value]
                and current[b] < self._MAX_PER_BAND
            ]
            if candidates:
                congested = max(candidates, key=lambda b: depths[b])
                self._logger.info(
                    "Scale-up: adding boost to %s band (depth=%d, threshold=%d)",
                    congested.value, depths[congested],
                    self._SCALE_UP_THRESHOLDS[congested.value],
                )
                self._add_worker(congested)
                self._boost_band = congested
                self._boost_empty_since = None

    # ── Worker management ─────────────────────────────────────────────

    def _add_worker(self, band: QueueBand) -> None:
        """Create and start a new daemon worker thread for *band*."""
        t = threading.Thread(
            target=self._worker_loop,
            args=(band,),
            name=f"worker-{band.value}",
            daemon=True,
        )
        t.start()
        self._workers[band].append(t)
        self._logger.debug("Added worker for %s band (total: %d)", band.value, len(self._workers[band]))

    def _remove_worker(self, band: QueueBand) -> bool:
        """Request one excess worker in *band* to exit gracefully.

        Returns ``True`` if a removal was requested, ``False`` if the
        band already has only its base worker.
        """
        if len(self._workers[band]) <= self._BASE_PER_BAND:
            return False
        self._workers_to_stop[band] += 1
        return True

    def _worker_loop(self, band: QueueBand) -> None:
        """Main loop for a single worker thread.

        Continuously dequeues items from the assigned band, acquires the
        platform semaphore, runs the live check, stores the result, and
        releases.
        """
        while not self._stop_event.is_set():
            try:
                # ── Self-removal check ───────────────────────────────
                # If this band has been told to shed a worker, we exit.
                if self._workers_to_stop.get(band, 0) > 0:
                    with self._lock:
                        self._workers_to_stop[band] -= 1
                        self._workers[band].remove(threading.current_thread())
                    self._logger.debug(
                        "Worker exiting (%s band) — boost removed",
                        band.value,
                    )
                    break

                item = self._queue_planner.dequeue_for_band(band)
                if item is None:
                    # No work — sleep a bit before polling again.
                    self._stop_event.wait(timeout=0.5)
                    continue

                stream_id, platform_key = item

                # ── Due validation ──────────────────────────────────
                if self._due_checker is not None and not self._due_checker(stream_id):
                    self._logger.debug(
                        "Discarding non-due item for stream %s (band=%s)",
                        stream_id, band.value,
                    )
                    continue

                # Small random stagger so external observers don't see
                # perfectly regular check patterns (StreamCap: 0.5-3s).
                time.sleep(random.uniform(0.5, 3.0))

                self._logger.info(
                    "Checking stream %s (%s band)",
                    stream_id, band.value,
                )
                self._semaphores.acquire_sync(platform_key)
                try:
                    result = self._live_check_service.check_stream(stream_id)
                    status = "LIVE" if result.is_live else "offline"
                    self._logger.info(
                        "Stream %s is %s (url=%s)",
                        stream_id,
                        status,
                        result.stream_url or "n/a",
                    )
                    if self._result_store is not None:
                        self._result_store.store(stream_id, result)
                finally:
                    self._semaphores.release_sync(platform_key)
            except Exception:
                self._logger.exception(
                    "Worker error in processing loop (%s band)",
                    band.value,
                )
                self._stop_event.wait(timeout=1.0)

    def _monitor_loop(self) -> None:
        """Periodically check queue depths and adjust worker allocation."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._MONITOR_INTERVAL)
            if self._stop_event.is_set():
                break

            fast = self._queue_planner.queue_depth(QueueBand.FAST)
            medium = self._queue_planner.queue_depth(QueueBand.MEDIUM)
            slow = self._queue_planner.queue_depth(QueueBand.SLOW)

            self._logger.debug(
                "Monitor: depths F=%d M=%d S=%d, workers=%s",
                fast,
                medium,
                slow,
                self.worker_count,
            )
            self.adjust_workers(fast, medium, slow)
