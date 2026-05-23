"""MonitoringCycle - runs in a background thread, periodically evaluating
all enabled stream targets, computing predictions, and enqueuing due
live checks to the priority queue system.

Minimal runtime state lives in memory only - it is reconstructed on
startup from :class:`RecordingSession` data and updated by each cycle.
Rich ``MonitoringSnapshot`` values are derived on demand for queries and
event payloads. This avoids stale-state bugs caused by persisted
snapshots that refer to dead ffmpeg processes after restart.

Flow per cycle
--------------
1. Load all enabled ``StreamTarget`` s.
2. For each target, load its in-memory runtime state (create a
   default if it does not exist yet).
3. Compute a fresh ``PredictionResult`` from the runtime state.
4. Update the in-memory runtime state with a jittered ``next_check_at``.
5. If a live check is due, enqueue to the ``QueuePlanner``.
6. After processing all targets, consume any pending ``ResolveResult``
   entries from worker threads, update in-memory runtime state,
   detect state transitions, and emit events.
"""

import logging
import threading
from datetime import datetime, timedelta

from app.application.services.live_check_result_store import (
    LiveCheckResultStore,
)
from app.application.services.recording_service import RecordingService
from app.domain.monitoring.runtime_state import MonitoringRuntimeState
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.prediction.engine import PredictionEngine
from app.domain.prediction.results import PredictionResult
from app.domain.prediction.policy import (
    apply_jitter,
    get_interval_seconds,
    get_queue_band,
)
from app.domain.shared.types import Confidence, QueueBand, UiState, utc_now
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

    Owns the in-memory runtime-state store for all stream targets.
    ``MonitoringSnapshot`` values are derived from that state when
    needed. Worker threads communicate resolve results back via the
    :class:`LiveCheckResultStore`.

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
        loop_interval_seconds: int = 180,
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

        # ── In-memory runtime-state store ──────────────────────
        self._runtime_states: dict[str, MonitoringRuntimeState] = {}

        # ── Last-known state cache (for event detection) ───────
        self._last_known_state: dict[str, MonitoringState] = {}
        self._last_known_live: dict[str, bool] = {}

        # ── Core-ready emission guard ─────────────────────────
        self._core_ready_emitted: bool = False

        # ── Per-cycle enqueue counters ─────────────────────────
        self._cycle_enqueued: dict[QueueBand, int] = {}



    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the monitoring loop in a daemon background thread.

        Before starting the loop, pre-builds in-memory runtime state for all
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
        """Load all targets and build initial in-memory runtime state.

        **Important**: Startup NEVER restores ``RECORDING`` state from
        persisted sessions - after a restart the ffmpeg process is gone.
        Runtime state always starts as idle, preserving only historical
        signal (``last_live_at``).  The first fresh live check will
        transition the derived snapshot to ``RECORDING`` normally.
        """
        # All targets start with next_check_at=now so the first cycle
        # queues them immediately.  Worker stagger (0.5-3s) and platform
        # semaphores regulate actual concurrency - no artificial delay
        # is needed, especially with a 180s cycle interval.
        targets = self._target_repo.list_all()
        now = utc_now()

        for target in targets:
            # Preserve historical live timestamp if available - but
            # do NOT assume a live stream is ongoing after restart.
            sessions = self._session_repo.list_by_target(target.id)
            last_live = sessions[0].started_at if sessions else None

            self._runtime_states[target.id] = MonitoringRuntimeState(
                stream_target_id=target.id,
                next_check_at=now,
                last_checked_at=None,
                last_live_at=last_live,
                is_live=False,
                active_recording_session_id=None,
                previous_likelihood=0.0,
                updated_at=now,
            )

            # Prime last-known state cache
            self._last_known_state[target.id] = MonitoringState.IDLE
            self._last_known_live[target.id] = False

        self._logger.info(
            "Built %d initial in-memory runtime states; first check queued immediately",
            len(self._runtime_states),
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

    def register_new_target(self, stream_id: str) -> None:
        """Register a runtime state for a newly added stream target.

        Sets ``next_check_at`` to *now* so the next cycle picks it up
        as due immediately.
        """
        now = utc_now()
        if stream_id not in self._runtime_states:
            self._runtime_states[stream_id] = MonitoringRuntimeState(
                stream_target_id=stream_id,
                next_check_at=now,
                last_checked_at=None,
                last_live_at=None,
                is_live=False,
                active_recording_session_id=None,
                previous_likelihood=0.0,
                updated_at=now,
            )
            # Prime last-known state cache
            self._last_known_state[stream_id] = MonitoringState.IDLE
            self._last_known_live[stream_id] = False
            self._logger.debug("Registered new target %s in runtime state", stream_id)

    def get_snapshot(self, stream_id: str) -> MonitoringSnapshot | None:
        """Return the derived snapshot for *stream_id*, or ``None``."""
        target = self._find_target(stream_id)
        if target is None:
            return None
        return self._build_snapshot(target)

    def get_all_snapshots(self) -> list[MonitoringSnapshot]:
        """Return derived snapshots for all known targets."""
        return [self._build_snapshot(target) for target in self._target_repo.list_all()]

    # ── Internal loop ─────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main loop body -- runs until ``stop()`` is signalled."""
        while not self._stop_event.is_set():
            try:
                self._run_one_cycle()
            except Exception:
                self._logger.exception(
                    "Unhandled error in monitoring cycle - continuing",
                )
            self._stop_event.wait(timeout=self._loop_interval)

    def _run_one_cycle(self) -> None:
        """Evaluate every enabled stream target once.

        Phase A - Process & Predict
            For each enabled target: load/create runtime state,
            compute prediction, update snapshot, enqueue if due.

        Phase B - Detect & React
            Consume ``ResolveResult`` entries from worker threads,
            apply them to runtime state, detect state transitions,
            emit events via the ``EventBus``, and start/stop recordings.
        """
        targets = self._target_repo.list_all()
        enabled = [t for t in targets if t.enabled]

        # Sort by priority (highest likelihood first) so streams with
        # the highest chance of being live are checked and enqueued
        # before less-urgent ones.
        enabled.sort(
            key=lambda t: self._runtime_states.get(
                t.id,
                MonitoringRuntimeState(
                    stream_target_id=t.id,
                    next_check_at=None,
                    last_checked_at=None,
                    last_live_at=None,
                    is_live=False,
                    active_recording_session_id=None,
                    previous_likelihood=0.0,
                    updated_at=utc_now(),
                ),
            ).previous_likelihood,
            reverse=True,
        )

        # Reset per-cycle enqueue counters
        self._cycle_enqueued = {band: 0 for band in QueueBand}

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
                runtime_state = self._get_or_create_runtime_state(target.id, now)

                # 1. Apply latest resolve result from worker threads
                result = self._result_store.consume(target.id)
                if result is not None:
                    runtime_state = self._apply_resolve_result(
                        runtime_state, result, now, target,
                    )
                    self._runtime_states[target.id] = runtime_state

                # 2. Check for externally stopped recordings
                #    (e.g. API-triggered stop via StopRecordingHandler)
                if runtime_state.active_recording_session_id is not None:
                    session = self._session_repo.get(
                        runtime_state.active_recording_session_id,
                    )
                    if session is None or not session.is_active:
                        # Recording was stopped externally - reset
                        runtime_state = self._clear_recording_state(runtime_state, now)
                        self._runtime_states[target.id] = runtime_state

                # Only emit events when we have a prior state in cache
                old_state = self._last_known_state.get(target.id)
                old_was_live = self._last_known_live.get(target.id)

                if old_state is not None:
                    # ── Live transition: start recording ──────────
                    if old_was_live is not None and runtime_state.is_live and not old_was_live:
                        if self._recording_service is not None and result is not None and result.stream_url:
                            try:
                                session_id = self._recording_service.start_recording(
                                    stream_target_id=target.id,
                                    stream_url=result.stream_url,
                                )
                                runtime_state = self._with_recording_session(
                                    runtime_state, session_id, now,
                                )
                                self._runtime_states[target.id] = runtime_state
                                snapshot = self._build_snapshot(target, runtime_state=runtime_state, now=now)
                            except Exception:
                                self._logger.exception(
                                    "Failed to start recording for %s (%s)",
                                    target.id,
                                    target.handle,
                                )

                    # ── Offline transition: stop recording ────────
                    if old_was_live is not None and not runtime_state.is_live and old_was_live:
                        if self._recording_service is not None and runtime_state.active_recording_session_id:
                            try:
                                self._recording_service.stop_recording(
                                    recording_session_id=runtime_state.active_recording_session_id,
                                )
                                runtime_state = self._clear_recording_state(
                                    runtime_state, now,
                                )
                                self._runtime_states[target.id] = runtime_state
                                snapshot = self._build_snapshot(target, runtime_state=runtime_state, now=now)
                            except Exception:
                                self._logger.exception(
                                    "Failed to stop recording for %s (%s)",
                                    target.id,
                                    target.handle,
                                )

                snapshot = self._build_snapshot(target, runtime_state=runtime_state, now=now)

                if old_state is not None and old_state != snapshot.state:
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

                # Update cache for next cycle
                self._last_known_state[target.id] = snapshot.state
                self._last_known_live[target.id] = runtime_state.is_live

            self._emit_queue_health()
            self._emit_cycle_stats(enabled, now)

        # ── Emit system.core_ready after first successful cycle ─
        if self._event_bus is not None and not self._core_ready_emitted:
            self._event_bus.publish("system.core_ready", {
                "target_count": len(self._runtime_states),
            })
            self._core_ready_emitted = True

        self._logger.info(
            "Monitoring cycle complete: %d/%d targets processed, "
            "%d enqueued, %d errors",
            processed,
            len(enabled),
            enqueued,
            errors,
        )

    # ── Due validation (called from WorkerPool) ────────────────────────

    def is_stream_due(self, stream_id: str) -> bool:
        """Lightweight memory check - should this dequeued item be processed?

        A stream is considered *still due* unless it was checked very
        recently by another worker.  This prevents redundant work when an
        item sits in a queue for a long time and another worker already
        processed it.

        Returns ``False`` only when ``last_checked_at`` is recent
        (within the last 60 seconds).
        """
        now = utc_now()
        state = self._runtime_states.get(stream_id)
        if state is None:
            return True
        if state.last_checked_at is None:
            return True
        return (now - state.last_checked_at).total_seconds() > 60

    # ── Per-target processing ─────────────────────────────────────────

    def _process_target(self, target: StreamTarget) -> bool:
        """Run one monitoring iteration for a single stream target.

        Steps
        -----
        1. Load the target's runtime state (create a
           default if none exists yet).
        2. Count recording sessions for the target.
        3. Compute a ``PredictionResult`` via ``PredictionEngine``.
        4. Update the in-memory runtime state with a
           jittered ``next_check_at``.
        5. If a live check is due, enqueue the target to the
           ``QueuePlanner`` and return ``True``.

        Returns
        -------
        bool
            ``True`` if the target was enqueued for a live check.
        """
        now = utc_now()
        runtime_state = self._get_or_create_runtime_state(target.id, now)
        snapshot = self._build_prediction_snapshot(runtime_state, now)

        # ── Check if a live check is due ─────────────────────────
        should_check = (
            runtime_state.next_check_at is None
            or runtime_state.next_check_at <= now
        )

        # ── Gather prediction context ────────────────────────────
        sessions = self._session_repo.list_by_target(target.id)
        session_count = len(sessions)
        previous_priority = runtime_state.previous_likelihood

        # ── Compute prediction (uses current snapshot) ───────────
        result = self._prediction_engine.predict(
            stream_target=target,
            snapshot=snapshot,
            previous_priority=previous_priority,
            session_count=session_count,
            period_days=self._period_days,
            _now=now,
        )

        # ── Determine interval and queue band ──────────────────
        interval = get_interval_seconds(result.likelihood, target.favorite)
        jittered = apply_jitter(interval)
        queue_band = get_queue_band(result.likelihood, target.favorite)

        # ── Determine next check time ──────────────────────────
        # Only push the deadline forward when we actually enqueue a check.
        # Preserving existing next_check_at when skipping avoids the
        # perpetual "0 enqueued" bug where every cycle resets the timer.
        if should_check:
            next_check_at = now + timedelta(seconds=jittered)
            self._queue_planner.enqueue(
                target.id,
                queue_band,
                target.platform.value,
            )
            self._cycle_enqueued[queue_band] = (
                self._cycle_enqueued.get(queue_band, 0) + 1
            )
            self._logger.info(
                "Dispatched %s (%s) to queue %s - next check at %s",
                target.id, target.handle, queue_band.value, next_check_at,
            )
        else:
            next_check_at = runtime_state.next_check_at
            # Skip is the common case - no need to log it.

        # ── Update in-memory runtime state ───────────────────────
        updated = MonitoringRuntimeState(
            stream_target_id=runtime_state.stream_target_id,
            next_check_at=next_check_at,
            last_checked_at=runtime_state.last_checked_at,
            last_live_at=runtime_state.last_live_at,
            is_live=runtime_state.is_live,
            active_recording_session_id=runtime_state.active_recording_session_id,
            previous_likelihood=result.likelihood,
            updated_at=now,
        )
        self._runtime_states[target.id] = updated

        # ── Prime last-known state for first-seen targets ─────
        if target.id not in self._last_known_state:
            self._last_known_state[target.id] = MonitoringState.IDLE
            self._last_known_live[target.id] = False

        return should_check

    # ── Resolve result application ────────────────────────────────────

    def _apply_resolve_result(
        self,
        runtime_state: MonitoringRuntimeState,
        result: ResolveResult,
        now: datetime,
        target: StreamTarget,
    ) -> MonitoringRuntimeState:
        """Merge a worker's resolve result into the in-memory runtime state."""
        if result.is_live:
            likelihood = 1.0
            last_live_at = now
        else:
            likelihood = 0.0
            last_live_at = runtime_state.last_live_at

        interval = get_interval_seconds(likelihood, target.favorite)
        jittered = apply_jitter(interval)

        return MonitoringRuntimeState(
            stream_target_id=runtime_state.stream_target_id,
            next_check_at=now + timedelta(seconds=jittered),
            last_checked_at=now,
            last_live_at=last_live_at,
            is_live=result.is_live,
            active_recording_session_id=runtime_state.active_recording_session_id,
            previous_likelihood=likelihood,
            updated_at=now,
        )

    # ── Runtime-state helpers ────────────────────────────────────────

    def _with_recording_session(
        self,
        runtime_state: MonitoringRuntimeState,
        session_id: str,
        now: datetime,
    ) -> MonitoringRuntimeState:
        """Return a runtime-state copy with active recording info set."""
        return MonitoringRuntimeState(
            stream_target_id=runtime_state.stream_target_id,
            next_check_at=runtime_state.next_check_at,
            last_checked_at=runtime_state.last_checked_at,
            last_live_at=runtime_state.last_live_at,
            is_live=runtime_state.is_live,
            active_recording_session_id=session_id,
            previous_likelihood=runtime_state.previous_likelihood,
            updated_at=now,
        )

    def _clear_recording_state(
        self,
        runtime_state: MonitoringRuntimeState,
        now: datetime,
    ) -> MonitoringRuntimeState:
        """Return a runtime-state copy with recording fields cleared."""
        return MonitoringRuntimeState(
            stream_target_id=runtime_state.stream_target_id,
            next_check_at=runtime_state.next_check_at,
            last_checked_at=runtime_state.last_checked_at,
            last_live_at=runtime_state.last_live_at,
            is_live=False,
            active_recording_session_id=None,
            previous_likelihood=0.0,
            updated_at=now,
        )

    def _get_or_create_runtime_state(
        self,
        stream_id: str,
        now: datetime,
    ) -> MonitoringRuntimeState:
        runtime_state = self._runtime_states.get(stream_id)
        if runtime_state is None:
            runtime_state = MonitoringRuntimeState(
                stream_target_id=stream_id,
                next_check_at=None,
                last_checked_at=None,
                last_live_at=None,
                is_live=False,
                active_recording_session_id=None,
                previous_likelihood=0.0,
                updated_at=now,
            )
            self._runtime_states[stream_id] = runtime_state
        return runtime_state

    def _find_target(self, stream_id: str) -> StreamTarget | None:
        target = None
        repo_get = getattr(self._target_repo, "get", None)
        if callable(repo_get):
            candidate = repo_get(stream_id)
            if isinstance(candidate, StreamTarget):
                target = candidate
        if target is not None:
            return target
        return next(
            (candidate for candidate in self._target_repo.list_all() if candidate.id == stream_id),
            None,
        )

    def _build_prediction_snapshot(
        self,
        runtime_state: MonitoringRuntimeState,
        now: datetime,
    ) -> MonitoringSnapshot:
        return MonitoringSnapshot(
            stream_target_id=runtime_state.stream_target_id,
            state=(
                MonitoringState.RECORDING
                if runtime_state.active_recording_session_id is not None
                else MonitoringState.IDLE
            ),
            queue_band=None,
            current_likelihood=runtime_state.previous_likelihood,
            current_confidence=Confidence.LOW,
            next_check_at=runtime_state.next_check_at,
            last_checked_at=runtime_state.last_checked_at,
            last_live_at=runtime_state.last_live_at,
            current_recording_session_id=runtime_state.active_recording_session_id,
            last_error_code=None,
            last_error_message=None,
            updated_at=runtime_state.updated_at,
        )

    def _build_snapshot(
        self,
        target: StreamTarget,
        runtime_state: MonitoringRuntimeState | None = None,
        now: datetime | None = None,
    ) -> MonitoringSnapshot:
        now = now or utc_now()
        runtime_state = runtime_state or self._get_or_create_runtime_state(target.id, now)
        prediction_snapshot = self._build_prediction_snapshot(runtime_state, now)
        sessions = self._session_repo.list_by_target(target.id)
        result = self._prediction_engine.predict(
            stream_target=target,
            snapshot=prediction_snapshot,
            previous_priority=runtime_state.previous_likelihood,
            session_count=len(sessions),
            period_days=self._period_days,
            _now=now,
        )
        if not isinstance(result, PredictionResult):
            result = PredictionResult(
                likelihood=runtime_state.previous_likelihood,
                confidence=Confidence.LOW,
                predicted_window_start=None,
                predicted_window_end=None,
                next_slot_at=None,
                ui_state=UiState.IDLE,
                reasons=[],
            )
        return MonitoringSnapshot(
            stream_target_id=target.id,
            state=prediction_snapshot.state,
            queue_band=get_queue_band(result.likelihood, target.favorite),
            current_likelihood=result.likelihood,
            current_confidence=result.confidence,
            next_check_at=runtime_state.next_check_at,
            last_checked_at=runtime_state.last_checked_at,
            last_live_at=runtime_state.last_live_at,
            current_recording_session_id=runtime_state.active_recording_session_id,
            last_error_code=None,
            last_error_message=None,
            updated_at=runtime_state.updated_at,
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

    def _emit_cycle_stats(
        self,
        enabled: list[StreamTarget],
        now: datetime,
    ) -> None:
        """Emit per-cycle queue statistics after Phase B."""
        if self._event_bus is None:
            return

        # Compute waiting counts from runtime state timers
        waiting: dict[str, int] = {"fast": 0, "medium": 0, "slow": 0}
        for target in enabled:
            state = self._runtime_states.get(target.id)
            if state is None:
                continue
            band = get_queue_band(state.previous_likelihood, target.favorite)
            if state.next_check_at is not None and state.next_check_at > now:
                waiting[band.value] += 1

        # Convert enqueued counters to string-keyed dict for JSON
        enqueued_payload: dict[str, int] = {
            band.value: self._cycle_enqueued.get(band, 0)
            for band in QueueBand
        }

        # Build workers-per-band payload
        workers_payload: dict[str, int] = {
            band.value: 0 for band in QueueBand
        }
        if self._worker_pool is not None:
            wc = self._worker_pool.worker_count
            for band in QueueBand:
                workers_payload[band.value] = wc.get(band, 0)

        self._event_bus.publish("queue.cycle_stats", {
            "enqueued": enqueued_payload,
            "waiting": waiting,
            "workers": workers_payload,
            "cycle_timestamp": now.isoformat(),
        })
