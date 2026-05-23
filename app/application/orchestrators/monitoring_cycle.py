"""MonitoringCycle — runs in a background thread, periodically evaluating
all enabled stream targets, computing predictions, and enqueuing due
live checks to the priority queue system.

Snapshots live in memory only — they are reconstructed on startup from
:class:`RecordingSession` data and updated by each monitoring cycle.
This avoids stale-state bugs caused by persisted snapshots that refer
to dead ffmpeg processes after restart.

Flow per cycle
--------------
1. Load all enabled ``StreamTarget`` s.
2. For each target, load its in-memory ``MonitoringSnapshot`` (create a
   default if it does not exist yet).
3. Compute a fresh ``PredictionResult`` via ``PredictionEngine``.
4. Update the in-memory snapshot with prediction data and a jittered
   ``next_check_at``.
5. If a live check is due, enqueue to the ``QueuePlanner``.
6. After processing all targets, consume any pending ``ResolveResult``
   entries from worker threads, update in-memory snapshots accordingly,
   detect state transitions, and emit events.
"""

import logging
import threading
from datetime import datetime, timedelta

from app.application.services.live_check_result_store import (
    LiveCheckResultStore,
)
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
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.infrastructure.resolvers.result import ResolveResult
from app.infrastructure.scheduler.queue_planner import QueuePlanner
from app.infrastructure.scheduler.worker_pool import WorkerPool


class MonitoringCycle:
    """Orchestrates the monitoring loop in a background thread.

    Owns the in-memory ``MonitoringSnapshot`` store for all stream
    targets.  Snapshots are built on startup from :class:`RecordingSession`
    data and updated on each cycle.  Worker threads communicate resolve
    results back via the :class:`LiveCheckResultStore`.

    Parameters
    ----------
    prediction_engine:
        Domain engine that computes likelihood, confidence, and UI state.
    stream_target_repo:
        Repository for ``StreamTarget`` entities.
    recording_session_repo:
        Repository for ``RecordingSession`` entities (used to count past
        sessions for prediction consistency and to restore snapshot state).
    result_store:
        Shared thread-safe store where workers write ``ResolveResult``
        entries, consumed on each cycle.
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
        recording_session_repo: RecordingSessionRepository,
        result_store: LiveCheckResultStore,
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
        self._session_repo = recording_session_repo
        self._result_store = result_store
        self._queue_planner = queue_planner
        self._logger = logger
        self._loop_interval = loop_interval_seconds
        self._period_days = period_days
        self._event_bus = event_bus
        self._worker_pool = worker_pool
        self._recording_service = recording_service

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # ── In-memory snapshot store ───────────────────────────
        self._snapshots: dict[str, MonitoringSnapshot] = {}

        # ── Last-known state cache (for event detection) ───────
        self._last_known_state: dict[str, MonitoringState] = {}
        self._last_known_live: dict[str, bool] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the monitoring loop in a daemon background thread.

        Before starting the loop, pre-builds in-memory snapshots for all
        stream targets from their recording sessions.
        """
        if self._thread is not None and self._thread.is_alive():
            self._logger.warning("MonitoringCycle is already running")
            return

        self._build_initial_snapshots()

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

    def _build_initial_snapshots(self) -> None:
        """Load all targets and build initial in-memory snapshots.

        For targets with an active recording session, the snapshot
        reflects RECORDING state so the cycle can manage it.
        """
        targets = self._target_repo.list_all()
        now = utc_now()

        for target in targets:
            # Check for an active recording session
            sessions = self._session_repo.list_by_target(target.id)
            active_session = next(
                (s for s in sessions if s.is_active),
                None,
            )

            if active_session is not None:
                state = MonitoringState.RECORDING
                recording_session_id = active_session.id
                likelihood = 1.0
                last_live_at = active_session.started_at
            else:
                state = MonitoringState.IDLE
                recording_session_id = None
                likelihood = 0.0
                last_live_at = None

            self._snapshots[target.id] = MonitoringSnapshot(
                stream_target_id=target.id,
                state=state,
                queue_band=None,
                current_likelihood=likelihood,
                current_confidence=Confidence.LOW,
                next_check_at=None,
                last_checked_at=None,
                last_live_at=last_live_at,
                current_recording_session_id=recording_session_id,
                resolved_stream_url=None,
                last_error_code=None,
                last_error_message=None,
                updated_at=now,
            )

            # Prime last-known state cache
            self._last_known_state[target.id] = state
            self._last_known_live[target.id] = (state == MonitoringState.RECORDING)

        self._logger.info(
            "Built %d initial in-memory snapshots", len(self._snapshots)
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

    # ── Public snapshot access ────────────────────────────────────────

    def get_snapshot(self, stream_id: str) -> MonitoringSnapshot | None:
        """Return the in-memory snapshot for *stream_id*, or ``None``."""
        return self._snapshots.get(stream_id)

    def get_all_snapshots(self) -> list[MonitoringSnapshot]:
        """Return all in-memory snapshots."""
        return list(self._snapshots.values())

    # ── Internal loop ─────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main loop body — runs until ``stop()`` is signalled."""
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

        Phase A — Process & Predict
            For each enabled target: load/create in-memory snapshot,
            compute prediction, update snapshot, enqueue if due.

        Phase B — Detect & React
            Consume ``ResolveResult`` entries from worker threads,
            apply them to in-memory snapshots, detect state transitions,
            emit events via the ``EventBus``, and start/stop recordings.
        """
        targets = self._target_repo.list_all()
        enabled = [t for t in targets if t.enabled]

        if not enabled:
            self._logger.debug("Monitoring cycle: no enabled targets")
            return

        processed = 0
        errors = 0
        enqueued = 0

        # ── Phase A: Process each target ──────────────────────────
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

        # ── Phase B: Detect state changes and emit events ─────────
        if self._event_bus is not None:
            now = utc_now()

            for target in enabled:
                snapshot = self._snapshots.get(target.id)
                if snapshot is None:
                    continue

                # 1. Apply latest resolve result from worker threads
                result = self._result_store.consume(target.id)
                if result is not None:
                    snapshot = self._apply_resolve_result(
                        snapshot, result, now,
                    )
                    self._snapshots[target.id] = snapshot

                # 2. Check for externally stopped recordings
                #    (e.g. API-triggered stop via StopRecordingHandler)
                if (
                    snapshot.is_live
                    and snapshot.current_recording_session_id is not None
                ):
                    session = self._session_repo.get(
                        snapshot.current_recording_session_id,
                    )
                    if session is None or not session.is_active:
                        # Recording was stopped externally — reset
                        snapshot = self._clear_recording_state(snapshot, now)
                        self._snapshots[target.id] = snapshot

                # Only emit events when we have a prior state in cache
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

                    # ── Live transition: start recording ──────────
                    if old_was_live is not None and snapshot.is_live and not old_was_live:
                        if self._recording_service is not None and snapshot.resolved_stream_url:
                            try:
                                session_id = self._recording_service.start_recording(
                                    stream_target_id=target.id,
                                    stream_url=snapshot.resolved_stream_url,
                                )
                                # Update in-memory snapshot with session id
                                self._snapshots[target.id] = self._with_recording_session(
                                    snapshot, session_id, snapshot.resolved_stream_url, now,
                                )
                            except Exception:
                                self._logger.exception(
                                    "Failed to start recording for %s (%s)",
                                    target.id,
                                    target.handle,
                                )

                    # ── Offline transition: stop recording ────────
                    if old_was_live is not None and not snapshot.is_live and old_was_live:
                        if self._recording_service is not None and snapshot.current_recording_session_id:
                            try:
                                self._recording_service.stop_recording(
                                    recording_session_id=snapshot.current_recording_session_id,
                                )
                                # Clear recording fields from in-memory snapshot
                                self._snapshots[target.id] = self._clear_recording_state(
                                    snapshot, now,
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
        1. Load the target's in-memory ``MonitoringSnapshot`` (create a
           default if none exists yet).
        2. Count recording sessions for the target.
        3. Compute a ``PredictionResult`` via ``PredictionEngine``.
        4. Update the in-memory snapshot with prediction data and a
           jittered ``next_check_at``.
        5. If a live check is due, enqueue the target to the
           ``QueuePlanner`` and return ``True``.

        Returns
        -------
        bool
            ``True`` if the target was enqueued for a live check.
        """
        now = utc_now()
        snapshot = self._snapshots.get(target.id)

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

        # ── Update in-memory snapshot ────────────────────────────
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
        self._snapshots[target.id] = updated

        # ── Prime last-known state for first-seen targets ─────
        if target.id not in self._last_known_state:
            self._last_known_state[target.id] = updated.state
            self._last_known_live[target.id] = updated.is_live

        # ── Enqueue for async check if due ───────────────────────
        if should_check:
            self._queue_planner.enqueue(
                target.id,
                queue_band,
                target.platform.value,
            )
            return True

        return False

    # ── Resolve result application ────────────────────────────────────

    def _apply_resolve_result(
        self,
        snapshot: MonitoringSnapshot,
        result: ResolveResult,
        now: datetime,
    ) -> MonitoringSnapshot:
        """Merge a worker's resolve result into the in-memory snapshot."""
        if result.is_live:
            state = MonitoringState.RECORDING
            likelihood = 1.0
            last_live_at = now
            resolved_stream_url = result.stream_url
        else:
            state = MonitoringState.IDLE
            likelihood = 0.0
            last_live_at = snapshot.last_live_at
            resolved_stream_url = None

        return MonitoringSnapshot(
            stream_target_id=snapshot.stream_target_id,
            state=state,
            queue_band=snapshot.queue_band,
            current_likelihood=likelihood,
            current_confidence=snapshot.current_confidence,
            next_check_at=snapshot.next_check_at,
            last_checked_at=now,
            last_live_at=last_live_at,
            current_recording_session_id=snapshot.current_recording_session_id,
            resolved_stream_url=resolved_stream_url,
            last_error_code=snapshot.last_error_code,
            last_error_message=snapshot.last_error_message,
            updated_at=now,
        )

    # ── Snapshot helpers for recording state ─────────────────────────

    def _with_recording_session(
        self,
        snapshot: MonitoringSnapshot,
        session_id: str,
        stream_url: str,
        now: datetime,
    ) -> MonitoringSnapshot:
        """Return a snapshot copy with recording session info set."""
        return MonitoringSnapshot(
            stream_target_id=snapshot.stream_target_id,
            state=snapshot.state,
            queue_band=snapshot.queue_band,
            current_likelihood=snapshot.current_likelihood,
            current_confidence=snapshot.current_confidence,
            next_check_at=snapshot.next_check_at,
            last_checked_at=snapshot.last_checked_at,
            last_live_at=snapshot.last_live_at,
            current_recording_session_id=session_id,
            resolved_stream_url=stream_url,
            last_error_code=snapshot.last_error_code,
            last_error_message=snapshot.last_error_message,
            updated_at=now,
        )

    def _clear_recording_state(
        self,
        snapshot: MonitoringSnapshot,
        now: datetime,
    ) -> MonitoringSnapshot:
        """Return a snapshot copy with recording fields cleared."""
        return MonitoringSnapshot(
            stream_target_id=snapshot.stream_target_id,
            state=MonitoringState.IDLE,
            queue_band=snapshot.queue_band,
            current_likelihood=0.0,
            current_confidence=snapshot.current_confidence,
            next_check_at=snapshot.next_check_at,
            last_checked_at=snapshot.last_checked_at,
            last_live_at=snapshot.last_live_at,
            current_recording_session_id=None,
            resolved_stream_url=None,
            last_error_code=snapshot.last_error_code,
            last_error_message=snapshot.last_error_message,
            updated_at=now,
        )

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
