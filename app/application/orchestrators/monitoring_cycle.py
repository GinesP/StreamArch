"""MonitoringCycle — runs in a background thread, periodically checking
all enabled stream targets, computing predictions, and triggering live
checks when needed.

Flow per cycle
--------------
1. Load all enabled ``StreamTarget`` s.
2. For each target, load its ``MonitoringSnapshot``.
3. Check if a live check is due (no ``next_check_at`` or it's in the past).
4. If due, run ``LiveCheckService.check_stream()`` and re-read the
   updated snapshot.
5. Compute a fresh ``PredictionResult`` via ``PredictionEngine``.
6. Persist the updated prediction state with a jittered ``next_check_at``.
"""

import logging
import threading
from datetime import datetime, timedelta

from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.prediction.engine import PredictionEngine
from app.domain.prediction.policy import apply_jitter, get_interval_seconds, get_queue_band
from app.domain.shared.types import Confidence, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.application.services.live_check_service import LiveCheckService


class MonitoringCycle:
    """Orchestrates the monitoring loop in a background thread.

    On each cycle every enabled target is evaluated sequentially (no
    parallel workers yet).  The class uses a ``threading.Event`` for
    clean shutdown — call ``stop()`` to signal the loop to exit.

    Parameters
    ----------
    prediction_engine:
        Domain engine that computes likelihood, confidence, and UI state.
    live_check_service:
        Application service that runs the resolver chain and persists
        check results.
    stream_target_repo:
        Repository for ``StreamTarget`` entities.
    monitoring_snapshot_repo:
        Repository for ``MonitoringSnapshot`` summaries.
    recording_session_repo:
        Repository for ``RecordingSession`` entities (used to count past
        sessions for prediction consistency).
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
        live_check_service: LiveCheckService,
        stream_target_repo: StreamTargetRepository,
        monitoring_snapshot_repo: MonitoringSnapshotRepository,
        recording_session_repo: RecordingSessionRepository,
        logger: logging.Logger,
        loop_interval_seconds: int = 15,
        period_days: float = 30.0,
    ) -> None:
        self._prediction_engine = prediction_engine
        self._live_check_service = live_check_service
        self._target_repo = stream_target_repo
        self._snapshot_repo = monitoring_snapshot_repo
        self._session_repo = recording_session_repo
        self._logger = logger
        self._loop_interval = loop_interval_seconds
        self._period_days = period_days

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

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
        errors encountered.
        """
        targets = self._target_repo.list_all()
        enabled = [t for t in targets if t.enabled]

        if not enabled:
            self._logger.debug("Monitoring cycle: no enabled targets")
            return

        processed = 0
        errors = 0

        for target in enabled:
            try:
                self._process_target(target)
                processed += 1
            except Exception:
                self._logger.exception(
                    "Error processing target %s (%s)",
                    target.id,
                    target.handle,
                )
                errors += 1

        self._logger.info(
            "Monitoring cycle complete: %d/%d targets processed, %d errors",
            processed,
            len(enabled),
            errors,
        )

    # ── Per-target processing ─────────────────────────────────────────

    def _process_target(self, target: StreamTarget) -> None:
        """Run one monitoring iteration for a single stream target.

        Steps
        -----
        1. Load the target's ``MonitoringSnapshot``.
        2. If no snapshot exists yet, create a default one.
        3. If ``next_check_at`` is ``None`` or in the past, trigger
           a live check via ``LiveCheckService.check_stream()``, then
           re-read the snapshot (the service may have updated it).
        4. Count recording sessions for the target to use as a
           consistency signal.
        5. Compute a ``PredictionResult`` via ``PredictionEngine``.
        6. Determine the next check interval (jittered) and persist
           the updated snapshot.
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

        if should_check:
            self._live_check_service.check_stream(target.id)
            # Re-read the snapshot — check_stream may have changed
            # state, last_live_at, last_checked_at, etc.
            snapshot = self._snapshot_repo.get(target.id)
            # Guard: if the target was deleted between the check and
            # the re-read, fall back to an empty snapshot.
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

        # ── Gather prediction context ────────────────────────────
        sessions = self._session_repo.list_by_target(target.id)
        session_count = len(sessions)
        previous_priority = snapshot.current_likelihood

        # ── Compute prediction ───────────────────────────────────
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

        # ── Persist updated snapshot ─────────────────────────────
        updated = MonitoringSnapshot(
            stream_target_id=snapshot.stream_target_id,
            state=snapshot.state,
            queue_band=get_queue_band(result.likelihood, target.favorite),
            current_likelihood=result.likelihood,
            current_confidence=result.confidence,
            next_check_at=next_check_at,
            last_checked_at=snapshot.last_checked_at,
            last_live_at=snapshot.last_live_at,
            current_recording_session_id=snapshot.current_recording_session_id,
            last_error_code=snapshot.last_error_code,
            last_error_message=snapshot.last_error_message,
            updated_at=now,
        )
        self._snapshot_repo.save(updated)
