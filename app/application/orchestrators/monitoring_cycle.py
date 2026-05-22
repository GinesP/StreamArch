"""MonitoringCycle — runs in a background thread, periodically evaluating
all enabled stream targets, computing predictions, and enqueuing due
live checks to the priority queue system.

Flow per cycle
--------------
1. Load all enabled ``StreamTarget`` s.
2. For each target, load its ``MonitoringSnapshot``.
3. Compute a fresh ``PredictionResult`` via ``PredictionEngine``.
4. Persist the updated prediction state with a jittered ``next_check_at``.
5. If a live check is due (no ``next_check_at`` or it is in the past),
   enqueue the target to the ``QueuePlanner`` so the ``WorkerPool``
   processes it asynchronously.
6. After processing all targets, detect state changes and emit events
   via the ``EventBus`` (``stream.status_changed``, ``recording.started``,
   ``queue.health_updated``).
"""

import logging
import threading
from datetime import datetime, timedelta

from app.application.services.recording_service import RecordingService
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.prediction.engine import PredictionEngine
from app.domain.prediction.policy import (
    apply_jitter,
    get_interval_seconds,
    get_queue_band,
)
from app.domain.shared.types import Confidence, QueueBand, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.infrastructure.events.event_bus import EventBus
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.infrastructure.scheduler.queue_planner import QueuePlanner
from app.infrastructure.scheduler.worker_pool import WorkerPool


class MonitoringCycle:
    """Orchestrates the monitoring loop in a background thread.

    On each cycle every enabled target is evaluated sequentially.  Targets
    that are due for a live check are enqueued to the ``QueuePlanner``
    instead of being checked inline — workers (see ``WorkerPool``) process
    them concurrently.

    The class uses a ``threading.Event`` for clean shutdown — call
    ``stop()`` to signal the loop to exit.

    Parameters
    ----------
    prediction_engine:
        Domain engine that computes likelihood, confidence, and UI state.
    stream_target_repo:
        Repository for ``StreamTarget`` entities.
    monitoring_snapshot_repo:
        Repository for ``MonitoringSnapshot`` summaries.
    recording_session_repo:
        Repository for ``RecordingSession`` entities (used to count past
        sessions for prediction consistency).
    queue_planner:
        Shared ``QueuePlanner`` to which due targets are enqueued for
        async processing by the ``WorkerPool``.
    logger:
        Logger for cycle-level and per-target log messages.
    loop_interval_seconds:
        How often (in seconds) the cycle should evaluate all targets.
    period_days:
        Observation window (in days) for session-count consistency.
    """

    def __init__(
        self,
        prediction_engine: PredictionEngine,
        stream_target_repo: StreamTargetRepository,
        monitoring_snapshot_repo: MonitoringSnapshotRepository,
        recording_session_repo: RecordingSessionRepository,
        queue_planner: QueuePlanner,
        logger: logging.Logger,
        loop_interval_seconds: int = 15,
        period_days: float = 30.0,
        event_bus: EventBus | None = None,
        worker_pool: WorkerPool | None = None,
        recording_service: RecordingService | None = None,
    ) -> None:
        self._prediction_engine = prediction_engine
        self._target_repo = stream_target_repo
        self._snapshot_repo = monitoring_snapshot_repo
        self._session_repo = recording_session_repo
        self._queue_planner = queue_planner
        self._logger = logger
        self._loop_interval = loop_interval_seconds
        self._period_days = period_days
        self._event_bus = event_bus
        self._worker_pool = worker_pool
        self._recording_service = recording_service

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # ── Last-known state cache (for event detection) ─────────
        self._last_known_state: dict[str, MonitoringState] = {}
        self._last_known_live: dict[str, bool] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the monitoring loop in a daemon background thread.

        If the cycle is already running this is a no-op (a warning is
        logged).
        """
        if self._thread is not None and self._thread.is_alive():
            self._logger.warning("MonitoringCycle is already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="monitoring-cycle",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "MonitoringCycle started (loop_interval=%ss, period_days=%s)",
            self._loop_interval,
            self._period_days,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the loop to stop and wait for the background thread.

        Args:
            timeout: Maximum seconds to wait for the thread to finish.
        """
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                self._logger.warning(
                    "MonitoringCycle thread did not stop within %ss",
                    timeout,
                )
            else:
                self._logger.info("MonitoringCycle stopped")

    @property
    def is_running(self) -> bool:
        """Whether the background thread is alive (started and not stopped)."""
        return self._thread is not None and self._thread.is_alive()

    # ── Internal loop ─────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main loop body — runs until ``stop()`` is signalled.

        Each iteration executes one full cycle then sleeps for
        *loop_interval_seconds*.  Unhandled exceptions are logged but
        do **not** kill the loop.
        """
        while not self._stop_event.is_set():
            try:
                self._run_one_cycle()
            except Exception:
                self._logger.exception(
                    "Unhandled error in monitoring cycle — continuing",
                )
            self._stop_event.wait(timeout=self._loop_interval)

    def _run_one_cycle(self) -> None:
        """Evaluate every enabled stream target once.

        Logs a summary with the number of targets processed and any
        errors encountered.  After processing, reads fresh snapshots
        from the repository to detect state transitions (which may have
        been changed by ``LiveCheckService`` in worker threads between
        cycles) and emits events via the ``EventBus``.
        """
        targets = self._target_repo.list_all()
        enabled = [t for t in targets if t.enabled]

        if not enabled:
            self._logger.debug("Monitoring cycle: no enabled targets")
            return

        processed = 0
        errors = 0
        enqueued = 0

        for target in enabled:
            try:
                if self._process_target(target):
                    enqueued += 1
                processed += 1
            except Exception:
                self._logger.exception(
                    "Error processing target %s (%s)",
                    target.id,
                    target.handle,
                )
                errors += 1

        # ── Detect state changes and emit events ──────────────────
        if self._event_bus is not None:
            for target in enabled:
                snapshot = self._snapshot_repo.get(target.id)
                if snapshot is None:
                    continue

                # Only emit events when we have a prior state in cache
                # (first cycle populates the cache; subsequent cycles detect
                # changes made by LiveCheckService in worker threads.)
                old_state = self._last_known_state.get(target.id)
                old_was_live = self._last_known_live.get(target.id)

                if old_state is not None:
                    if old_state != snapshot.state:
                        self._event_bus.publish(
                            "stream.status_changed",
                            {
                                "stream_id": target.id,
                                "state": snapshot.state.value,
                                "queue_band": snapshot.queue_band.value
                                if snapshot.queue_band else None,
                                "likelihood": snapshot.current_likelihood,
                                "confidence": snapshot.current_confidence.value,
                                "ui_state": snapshot.state.value,
                            },
                        )

                    # ── Live transition: start recording ──────────────
                    if old_was_live is not None and snapshot.is_live and not old_was_live:
                        if self._recording_service is not None and snapshot.resolved_stream_url:
                            try:
                                self._recording_service.start_recording(
                                    stream_target_id=target.id,
                                    stream_url=snapshot.resolved_stream_url,
                                )
                            except Exception:
                                self._logger.exception(
                                    "Failed to start recording for %s (%s)",
                                    target.id,
                                    target.handle,
                                )

                    # ── Offline transition: stop recording ───────────
                    if old_was_live is not None and not snapshot.is_live and old_was_live:
                        if self._recording_service is not None and snapshot.current_recording_session_id:
                            try:
                                self._recording_service.stop_recording(
                                    recording_session_id=snapshot.current_recording_session_id,
                                )
                            except Exception:
                                self._logger.exception(
                                    "Failed to stop recording for %s (%s)",
                                    target.id,
                                    target.handle,
                                )

                # Update cache for next cycle
                self._last_known_state[target.id] = snapshot.state
                self._last_known_live[target.id] = snapshot.is_live

            self._emit_queue_health()

        self._logger.info(
            "Monitoring cycle complete: %d/%d targets processed, "
            "%d enqueued, %d errors",
            processed,
            len(enabled),
            enqueued,
            errors,
        )

    # ── Per-target processing ─────────────────────────────────────────

    def _process_target(self, target: StreamTarget) -> bool:
        """Run one monitoring iteration for a single stream target.

        Steps
        -----
        1. Load the target's ``MonitoringSnapshot`` (create a default if
           none exists yet).
        2. Count recording sessions for the target.
        3. Compute a ``PredictionResult`` via ``PredictionEngine``.
        4. Persist the updated snapshot with prediction data and a
           jittered ``next_check_at``.
        5. If a live check is due (``next_check_at`` was ``None`` or in
           the past), enqueue the target to the ``QueuePlanner`` and
           return ``True``.

        Returns
        -------
        bool
            ``True`` if the target was enqueued for a live check.
        """
        now = utc_now()
        snapshot = self._snapshot_repo.get(target.id)

        # ── Ensure a snapshot exists for prediction ──────────────
        if snapshot is None:
            snapshot = MonitoringSnapshot(
                stream_target_id=target.id,
                state=MonitoringState.IDLE,
                queue_band=None,
                current_likelihood=0.0,
                current_confidence=Confidence.LOW,
                next_check_at=None,
                last_checked_at=None,
                last_live_at=None,
                current_recording_session_id=None,
                last_error_code=None,
                last_error_message=None,
                updated_at=now,
            )

        # ── Check if a live check is due ─────────────────────────
        should_check = (
            snapshot.next_check_at is None
            or snapshot.next_check_at <= now
        )

        # ── Gather prediction context ────────────────────────────
        sessions = self._session_repo.list_by_target(target.id)
        session_count = len(sessions)
        previous_priority = snapshot.current_likelihood

        # ── Compute prediction (uses current snapshot) ───────────
        result = self._prediction_engine.predict(
            stream_target=target,
            snapshot=snapshot,
            previous_priority=previous_priority,
            session_count=session_count,
            period_days=self._period_days,
            _now=now,
        )

        # ── Determine the next check time (with jitter) ──────────
        interval = get_interval_seconds(result.likelihood, target.favorite)
        jittered = apply_jitter(interval)
        next_check_at = now + timedelta(seconds=jittered)

        queue_band = get_queue_band(result.likelihood, target.favorite)

        # ── Persist updated snapshot (preserve recording fields) ──
        updated = MonitoringSnapshot(
            stream_target_id=snapshot.stream_target_id,
            state=snapshot.state,
            queue_band=queue_band,
            current_likelihood=result.likelihood,
            current_confidence=result.confidence,
            next_check_at=next_check_at,
            last_checked_at=snapshot.last_checked_at,
            last_live_at=snapshot.last_live_at,
            current_recording_session_id=snapshot.current_recording_session_id,
            resolved_stream_url=snapshot.resolved_stream_url,
            last_error_code=snapshot.last_error_code,
            last_error_message=snapshot.last_error_message,
            updated_at=now,
        )
        self._snapshot_repo.save(updated)

        # ── Enqueue for async check if due ───────────────────────
        if should_check:
            self._queue_planner.enqueue(
                target.id,
                queue_band,
                target.platform.value,
            )
            return True

        return False

    # ── Event emission (helpers) ──────────────────────────────────────

    def _emit_queue_health(self) -> None:
        """Emit periodic queue health summary."""
        payload: dict[str, dict[str, int]] = {}
        for band in QueueBand:
            depth = self._queue_planner.queue_depth(band)
            workers = 0
            if self._worker_pool is not None:
                wc = self._worker_pool.worker_count
                workers = wc.get(band, 0)
            payload[band.value] = {
                "depth": depth,
                "workers": workers,
            }

        self._event_bus.publish("queue.health_updated", payload)
