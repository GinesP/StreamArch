"""Tests for MonitoringCycle — orchestrator that runs in a background
thread, periodically evaluating all enabled stream targets, computing
predictions, and enqueuing due live checks to the queue system.

All external dependencies (repositories, prediction engine, queue
planner) are mocked so these tests are fast, deterministic, and isolated.
Snapshots are in-memory, owned by the cycle itself.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.application.orchestrators.monitoring_cycle import MonitoringCycle
from app.application.services.live_check_result_store import (
    LiveCheckResultStore,
)
from app.domain.monitoring.runtime_state import MonitoringRuntimeState
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.prediction.results import PredictionResult
from app.domain.shared.types import Confidence, Platform, QueueBand, UiState
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode


# ── Helpers ─────────────────────────────────────────────────────────────


NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


def _target(**overrides) -> StreamTarget:
    return StreamTarget(
        id=overrides.get("id", "t1"),
        platform=overrides.get("platform", Platform.TWITCH),
        handle=overrides.get("handle", "streamer"),
        source_url=overrides.get("source_url", "https://twitch.tv/streamer"),
        display_name=overrides.get("display_name", "Streamer"),
        enabled=overrides.get("enabled", True),
        favorite=overrides.get("favorite", False),
        preferred_quality=overrides.get("preferred_quality", None),
        output_profile_id=overrides.get("output_profile_id", None),
        schedule_mode=overrides.get("schedule_mode", ScheduleMode.NONE),
        created_at=overrides.get("created_at", NOW),
        updated_at=overrides.get("updated_at", NOW),
    )


def _snapshot(**overrides) -> MonitoringSnapshot:
    return MonitoringSnapshot(
        stream_target_id=overrides.get("stream_target_id", "t1"),
        state=overrides.get("state", MonitoringState.IDLE),
        queue_band=overrides.get("queue_band", None),
        current_likelihood=overrides.get("current_likelihood", 0.5),
        current_confidence=overrides.get("current_confidence", Confidence.MEDIUM),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", NOW - timedelta(days=7)),
        current_recording_session_id=overrides.get("current_recording_session_id", None),
        last_error_code=overrides.get("last_error_code", None),
        last_error_message=overrides.get("last_error_message", None),
        updated_at=overrides.get("updated_at", NOW),
    )


def _runtime_state(**overrides) -> MonitoringRuntimeState:
    return MonitoringRuntimeState(
        stream_target_id=overrides.get("stream_target_id", "t1"),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", NOW - timedelta(days=7)),
        is_live=overrides.get("is_live", False),
        active_recording_session_id=overrides.get("active_recording_session_id", None),
        previous_likelihood=overrides.get("previous_likelihood", 0.5),
        updated_at=overrides.get("updated_at", NOW),
    )


def _result(**overrides) -> PredictionResult:
    return PredictionResult(
        likelihood=overrides.get("likelihood", 0.5),
        confidence=overrides.get("confidence", Confidence.MEDIUM),
        predicted_window_start=overrides.get("predicted_window_start", NOW),
        predicted_window_end=overrides.get(
            "predicted_window_end",
            NOW + timedelta(seconds=300),
        ),
        next_slot_at=overrides.get("next_slot_at", NOW),
        ui_state=overrides.get("ui_state", UiState.UPCOMING),
        reasons=overrides.get("reasons", []),
    )


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test")


@pytest.fixture
def mock_repos() -> dict:
    """Return fresh MagicMock instances for required repositories."""
    return {
        "target_repo": MagicMock(),
        "session_repo": MagicMock(),
    }


@pytest.fixture
def mock_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_queue_planner() -> MagicMock:
    return MagicMock()


@pytest.fixture
def result_store() -> LiveCheckResultStore:
    return LiveCheckResultStore()


@pytest.fixture
def cycle(
    mock_engine: MagicMock,
    mock_queue_planner: MagicMock,
    mock_repos: dict,
    result_store: LiveCheckResultStore,
    logger: logging.Logger,
) -> MonitoringCycle:
    """Return a MonitoringCycle with all dependencies mocked.

    The cycle is **not started** — call ``cycle.start()`` explicitly
    or invoke ``_run_one_cycle()`` directly in tests.
    """
    return MonitoringCycle(
        prediction_engine=mock_engine,
        stream_target_repo=mock_repos["target_repo"],
        recording_session_repo=mock_repos["session_repo"],
        result_store=result_store,
        queue_planner=mock_queue_planner,
        logger=logger,
        loop_interval_seconds=3600,  # 1 hour — prevents accidental wake-up
        period_days=30.0,
    )


# ======================================================================
# Cycle behaviour — no threading (direct _run_one_cycle calls)
# ======================================================================


class TestCycleEmptyTargets:
    """When there are no enabled targets, the cycle is a no-op."""

    def test_logs_debug_on_empty_enabled(self, cycle, mock_repos, caplog) -> None:
        caplog.set_level(logging.DEBUG)
        mock_repos["target_repo"].list_all.return_value = []

        cycle._run_one_cycle()

        assert "no enabled targets" in caplog.text
        mock_repos["session_repo"].list_by_target.assert_not_called()

    def test_skips_disabled_targets(self, cycle, mock_repos, caplog) -> None:
        caplog.set_level(logging.DEBUG)
        t1 = _target(id="t1", enabled=False)
        t2 = _target(id="t2", enabled=False)
        mock_repos["target_repo"].list_all.return_value = [t1, t2]

        cycle._run_one_cycle()

        assert "no enabled targets" in caplog.text


class TestCycleSingleTarget:
    """Happy path — one enabled target with an existing snapshot."""

    def process_target(
        self,
        cycle,
        mock_repos,
        mock_engine,
        mock_queue_planner,
        target_id="t1",
        next_check_at=None,
        return_result=None,
        now=NOW,
    ) -> None:
        """Helper: run one cycle with a single enabled target.

        Pre-populates an in-memory snapshot for the target.
        *now* is injected as the fixed current time so time-based
        assertions are deterministic.
        """
        target = _target(id=target_id)
        mock_repos["target_repo"].list_all.return_value = [target]

        # Pre-populate in-memory snapshot
        runtime_state = _runtime_state(
            stream_target_id=target_id,
            next_check_at=next_check_at,
        )
        cycle._runtime_states[target_id] = runtime_state

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = return_result or _result()
        mock_engine.predict.return_value = result

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=now,
        ):
            cycle._run_one_cycle()
        return runtime_state

    def test_processes_enabled_target(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Enabled target with snapshot — predicts and updates in-memory."""
        self.process_target(cycle, mock_repos, mock_engine, mock_queue_planner)

        # Prediction was called
        mock_engine.predict.assert_called_once()
        # In-memory snapshot was updated
        updated = cycle.get_snapshot("t1")
        assert updated is not None
        # Enqueued for async check (no next_check_at)
        mock_queue_planner.enqueue.assert_called_once_with(
            "t1", QueueBand.MEDIUM, "twitch",
        )

    def test_enqueues_when_next_check_at_is_none(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """No next_check_at → target is enqueued."""
        self.process_target(
            cycle, mock_repos, mock_engine, mock_queue_planner,
            next_check_at=None,
        )
        mock_queue_planner.enqueue.assert_called_once()

    def test_enqueues_when_next_check_at_is_past(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """next_check_at in the past → target is enqueued."""
        self.process_target(
            cycle, mock_repos, mock_engine, mock_queue_planner,
            next_check_at=NOW - timedelta(seconds=10),
        )
        mock_queue_planner.enqueue.assert_called_once()

    def test_skips_enqueue_when_next_check_at_is_future(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """next_check_at in the future → no enqueue."""
        self.process_target(
            cycle, mock_repos, mock_engine, mock_queue_planner,
            next_check_at=NOW + timedelta(seconds=300),
        )
        mock_queue_planner.enqueue.assert_not_called()

    def test_multi_cycle_enforces_deadline(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Multi-cycle: due → enqueue + deadline; before due → skip, no
        deadline push; after due → enqueue again.

        Verifies fix for the perpetual ``0 enqueued`` bug: before the fix,
        every cycle unconditionally reset ``next_check_at`` to
        ``now + interval``, so a target that was NOT due would still have
        its deadline pushed forward — making it NEVER due again.

        This test must fail before the fix and pass after.
        """
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]
        sessions: list = []
        mock_repos["session_repo"].list_by_target.return_value = sessions
        result = _result(likelihood=0.5, confidence=Confidence.MEDIUM)
        mock_engine.predict.return_value = result

        # ── Cycle A at NOW (no next_check_at → due) ─────────────
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()
        mock_queue_planner.enqueue.assert_called_once()
        snap_a = cycle.get_snapshot("t1")
        assert snap_a.next_check_at is not None
        assert snap_a.next_check_at > NOW
        deadline = snap_a.next_check_at  # remember the deadline

        # ── Cycle B at NOW + 1min (before due → SKIP) ──────────
        mock_queue_planner.reset_mock()
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW + timedelta(minutes=1),
        ):
            cycle._run_one_cycle()
        mock_queue_planner.enqueue.assert_not_called()
        snap_b = cycle.get_snapshot("t1")
        # CRITICAL: next_check_at MUST be preserved, NOT pushed forward
        assert snap_b.next_check_at == deadline, (
            f"next_check_at mutated from {deadline} to {snap_b.next_check_at}"
        )

        # ── Cycle C at NOW + 10min (after due → enqueue again) ─
        mock_queue_planner.reset_mock()
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW + timedelta(minutes=10),
        ):
            cycle._run_one_cycle()
        mock_queue_planner.enqueue.assert_called_once()
        snap_c = cycle.get_snapshot("t1")
        assert snap_c.next_check_at is not None
        assert snap_c.next_check_at > NOW + timedelta(minutes=10)

    def test_prediction_uses_current_snapshot(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Prediction uses the in-memory snapshot as loaded."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        cycle._runtime_states["t1"] = _runtime_state(stream_target_id="t1")

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result(likelihood=0.3, confidence=Confidence.LOW)
        mock_engine.predict.return_value = result

        cycle._run_one_cycle()

        # Prediction used the initial snapshot
        predict_call = mock_engine.predict.call_args
        assert predict_call is not None
        assert predict_call.kwargs["snapshot"].stream_target_id == "t1"
        assert predict_call.kwargs["snapshot"].last_live_at == NOW - timedelta(days=7)

    def test_creates_snapshot_for_new_target(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Target with no in-memory snapshot gets a default before processing."""
        target = _target(id="new_target")
        mock_repos["target_repo"].list_all.return_value = [target]
        # No snapshot in memory

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result(likelihood=0.3, confidence=Confidence.LOW)
        mock_engine.predict.return_value = result

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        # Enqueued because no next_check_at
        mock_queue_planner.enqueue.assert_called_once_with(
            "new_target", QueueBand.SLOW, "twitch",
        )

        # Snapshot was created in memory
        snap = cycle.get_snapshot("new_target")
        assert snap is not None
        assert snap.stream_target_id == "new_target"
        assert snap.current_likelihood == 0.3
        assert snap.current_confidence == Confidence.LOW

    def test_prediction_data_flows_to_snapshot(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Prediction engine output is correctly mapped to the in-memory snapshot."""
        target = _target(id="t1", favorite=True)
        mock_repos["target_repo"].list_all.return_value = [target]

        cycle._runtime_states["t1"] = _runtime_state(stream_target_id="t1", next_check_at=None)

        sessions = [MagicMock(), MagicMock()]  # 2 sessions
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result(
            likelihood=0.85,
            confidence=Confidence.HIGH,
            ui_state=UiState.EXPECTED_NOW,
        )
        mock_engine.predict.return_value = result

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        snap = cycle.get_snapshot("t1")
        assert snap is not None
        assert snap.current_likelihood == 0.85
        assert snap.current_confidence == Confidence.HIGH
        # Time-based assertions: next_check_at should be NOW + jittered interval
        assert snap.next_check_at is not None
        assert snap.next_check_at > NOW
        # Favourite with high likelihood → FAST or MEDIUM band
        assert snap.queue_band in (QueueBand.FAST, QueueBand.MEDIUM)

    def test_provides_session_count_to_engine(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """The number of recording sessions is passed to the prediction engine."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        cycle._runtime_states["t1"] = _runtime_state(stream_target_id="t1")

        sessions = [MagicMock(), MagicMock(), MagicMock()]  # 3 sessions
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result()
        mock_engine.predict.return_value = result

        cycle._run_one_cycle()

        mock_engine.predict.assert_called_once()
        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs["session_count"] == 3
        assert call_kwargs["period_days"] == 30.0

    def test_uses_current_likelihood_as_previous_priority(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """The snapshot's current_likelihood is passed as previous_priority."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        cycle._runtime_states["t1"] = _runtime_state(
            stream_target_id="t1",
            previous_likelihood=0.77,
        )

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result()
        mock_engine.predict.return_value = result

        cycle._run_one_cycle()

        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs["previous_priority"] == 0.77

    def test_records_error_count(
        self, cycle, mock_repos, mock_engine, mock_queue_planner, caplog
    ) -> None:
        """When a target raises, the error is logged and cycle continues."""
        caplog.set_level(logging.INFO)

        t1 = _target(id="t1")
        t2 = _target(id="t2")
        mock_repos["target_repo"].list_all.return_value = [t1, t2]

        # Pre-populate in-memory snapshots
        cycle._runtime_states["t1"] = _runtime_state(
            stream_target_id="t1", next_check_at=NOW + timedelta(hours=1),
        )
        cycle._runtime_states["t2"] = _runtime_state(
            stream_target_id="t2", next_check_at=NOW + timedelta(hours=1),
        )

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        # First predict succeeds, second predict raises.
        mock_engine.predict.side_effect = [_result(), ValueError("boom")]

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        assert "1 errors" in caplog.text
        assert "Error processing target t2" in caplog.text


# ======================================================================
# Startup — stale recording sessions (bugfix regression)
# ======================================================================


class TestStartupWithStaleSessions:
    """Startup NEVER restores RECORDING state from persisted sessions.

    After a restart, stale sessions in the DB with status ``recording``
    are just that — stale.  There is no ffmpeg process backing them.
    The snapshot must start as ``IDLE`` so the first live check can
    transition to ``RECORDING`` normally.
    """

    def test_stale_recording_session_does_not_produce_recording_snapshot(
        self, mock_repos, mock_engine, mock_queue_planner, result_store, logger,
    ) -> None:
        """Given a target with a stale RECORDING session, the initial
        snapshot is IDLE, not RECORDING."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        stale_session = RecordingSession(
            id="stale-session-1",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=2),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=2),
        )
        mock_repos["session_repo"].list_by_target.return_value = [stale_session]

        cycle = MonitoringCycle(
            prediction_engine=mock_engine,
            stream_target_repo=mock_repos["target_repo"],
            recording_session_repo=mock_repos["session_repo"],
            result_store=result_store,
            queue_planner=mock_queue_planner,
            logger=logger,
            loop_interval_seconds=3600,
            period_days=30.0,
        )

        cycle._build_initial_snapshots()

        snap = cycle.get_snapshot("t1")
        assert snap is not None
        assert snap.state == MonitoringState.IDLE, (
            f"Expected IDLE, got {snap.state.value}"
        )
        assert snap.is_live is False
        assert snap.current_recording_session_id is None
        # Historical signal is preserved
        assert snap.last_live_at is not None
        # Last-known live cache must be False
        assert cycle._last_known_live.get("t1") is False

    def test_fresh_live_check_can_start_recording_after_restart(
        self, mock_repos, mock_engine, mock_queue_planner, result_store, logger,
    ) -> None:
        """After restart with a stale session, a fresh live resolve result
        must be able to transition the snapshot to RECORDING and start a
        new recording session.

        This tests the full flow: _build_initial_snapshots (IDLE) →
        _run_one_cycle → Phase B consumes ResolveResult → RECORDING.
        """
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        stale_session = RecordingSession(
            id="stale-session-1",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=2),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=2),
        )
        mock_repos["session_repo"].list_by_target.return_value = [stale_session]

        # Mock prediction engine returns not-live prediction
        mock_engine.predict.return_value = _result(likelihood=0.0, confidence=Confidence.LOW)

        mock_recording_service = MagicMock()

        cycle = MonitoringCycle(
            prediction_engine=mock_engine,
            stream_target_repo=mock_repos["target_repo"],
            recording_session_repo=mock_repos["session_repo"],
            result_store=result_store,
            queue_planner=mock_queue_planner,
            logger=logger,
            loop_interval_seconds=3600,
            period_days=30.0,
            event_bus=MagicMock(),
            recording_service=mock_recording_service,
        )

        # Phase 1: build initial snapshots — must be IDLE
        cycle._build_initial_snapshots()
        snap = cycle.get_snapshot("t1")
        assert snap is not None
        assert snap.state == MonitoringState.IDLE
        assert snap.current_recording_session_id is None

        # Phase 2: simulate a fresh live check result
        from app.infrastructure.resolvers.result import ResolveResult
        live_result = ResolveResult(
            is_live=True,
            stream_url="https://live-stream.example.com/stream.m3u8",
        )
        # Manually inject into result store, then run one cycle
        result_store.store(target.id, live_result)

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        # Phase 3: the cycle should have consumed the result and
        # triggered start_recording on the recording service
        assert mock_recording_service.start_recording.called, (
            "start_recording should have been called after live result"
        )
        call_args = mock_recording_service.start_recording.call_args
        assert call_args.kwargs["stream_target_id"] == "t1"

        # In-memory snapshot should now show recording state
        snap = cycle.get_snapshot("t1")
        assert snap is not None
        assert snap.state == MonitoringState.RECORDING

    def test_no_stale_session_produces_idle_no_last_live(
        self, mock_repos, mock_engine, mock_queue_planner, result_store, logger,
    ) -> None:
        """Target with no sessions at all produces IDLE with None last_live_at."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]
        mock_repos["session_repo"].list_by_target.return_value = []

        cycle = MonitoringCycle(
            prediction_engine=mock_engine,
            stream_target_repo=mock_repos["target_repo"],
            recording_session_repo=mock_repos["session_repo"],
            result_store=result_store,
            queue_planner=mock_queue_planner,
            logger=logger,
            loop_interval_seconds=3600,
            period_days=30.0,
        )
        cycle._build_initial_snapshots()

        snap = cycle.get_snapshot("t1")
        assert snap is not None
        assert snap.state == MonitoringState.IDLE
        assert snap.current_recording_session_id is None
        assert snap.last_live_at is None

    def test_multiple_targets_only_stale_ones_start_idle(
        self, mock_repos, mock_engine, mock_queue_planner, result_store, logger,
    ) -> None:
        """Multiple targets: ALL get IDLE regardless of stale sessions."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        t1 = _target(id="t1")
        t2 = _target(id="t2")
        mock_repos["target_repo"].list_all.return_value = [t1, t2]

        stale = RecordingSession(
            id="stale",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=1),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )

        def list_by_target(target_id: str):
            return [stale] if target_id == "t1" else []

        mock_repos["session_repo"].list_by_target.side_effect = list_by_target

        cycle = MonitoringCycle(
            prediction_engine=mock_engine,
            stream_target_repo=mock_repos["target_repo"],
            recording_session_repo=mock_repos["session_repo"],
            result_store=result_store,
            queue_planner=mock_queue_planner,
            logger=logger,
            loop_interval_seconds=3600,
            period_days=30.0,
        )
        cycle._build_initial_snapshots()

        for tid in ("t1", "t2"):
            snap = cycle.get_snapshot(tid)
            assert snap is not None
            assert snap.state == MonitoringState.IDLE, f"{tid} should be IDLE"
            assert snap.current_recording_session_id is None


# ======================================================================
# Resolve result coherence — next_check_at / queue_band must be
# consistent with the resolved outcome
# ======================================================================


class TestResolveResultCoherence:
    """Direct unit tests for ``_apply_resolve_result``.

    These tests call the method directly with controlled inputs rather
    than going through the full cycle — this avoids the dependency on
    ``event_bus`` (which gates Phase B) and produces more focused
    assertions on the coherence fix.
    """

    # ── Helpers ───────────────────────────────────────────────────

    def _apply(
        self,
        cycle: MonitoringCycle,
        runtime_state: MonitoringRuntimeState,
        is_live: bool,
        stream_url: str | None = None,
        is_favorite: bool = False,
        now: datetime = NOW,
    ) -> MonitoringRuntimeState:
        """Thin wrapper around ``_apply_resolve_result``."""
        from app.infrastructure.resolvers.result import ResolveResult

        result = ResolveResult(
            is_live=is_live,
            stream_url=stream_url,
        )
        target = _target(id=runtime_state.stream_target_id, favorite=is_favorite)
        return cycle._apply_resolve_result(runtime_state, result, now, target)

    # ── Live resolve ────────────────────────────────────────────────

    def test_live_resolve_sets_fast_band_and_near_fast_next_check(
        self, cycle,
    ) -> None:
        """Live resolve overwrites stale MEDIUM queue_band/next_check_at
        with FAST values."""
        stale = _runtime_state(
            stream_target_id="t1",
            previous_likelihood=0.5,
            next_check_at=NOW + timedelta(seconds=300),
        )

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            updated = self._apply(cycle, stale, is_live=True)

        updated_snapshot = cycle._build_snapshot(_target(id="t1"), runtime_state=updated, now=NOW)
        assert updated_snapshot.state == MonitoringState.IDLE
        assert updated_snapshot.current_likelihood == 1.0
        assert updated_snapshot.queue_band == QueueBand.FAST
        # FAST interval = 60s, jitter ±15% = ±9s → range [51, 69]
        assert updated.next_check_at is not None
        assert NOW + timedelta(seconds=50) <= updated.next_check_at <= NOW + timedelta(seconds=70), (
            f"next_check_at {updated.next_check_at} outside FAST range"
        )
        # last_checked_at was bumped
        assert updated.last_checked_at == NOW

    def test_live_resolve_with_favorite_target(
        self, cycle,
    ) -> None:
        """Even favourite targets get FAST band after live resolve —
        likelihood=1.0 exceeds the fast threshold regardless."""
        stale = _runtime_state(
            stream_target_id="t1",
            previous_likelihood=0.5,
            next_check_at=NOW + timedelta(seconds=300),
        )

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            updated = self._apply(cycle, stale, is_live=True, is_favorite=True,
                                  stream_url="https://example.com/stream.m3u8")

        updated_snapshot = cycle._build_snapshot(
            _target(id="t1", favorite=True), runtime_state=updated, now=NOW,
        )
        assert updated_snapshot.state == MonitoringState.IDLE
        assert updated_snapshot.current_likelihood == 1.0
        assert updated_snapshot.queue_band == QueueBand.FAST

    # ── Offline resolve ─────────────────────────────────────────────

    def test_offline_resolve_sets_slow_band(
        self, cycle,
    ) -> None:
        """Offline resolve overwrites stale FAST timing with SLOW values."""
        stale = _runtime_state(
            stream_target_id="t1",
            previous_likelihood=0.95,
            next_check_at=NOW + timedelta(seconds=60),
        )

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            updated = self._apply(cycle, stale, is_live=False)

        updated_snapshot = cycle._build_snapshot(_target(id="t1"), runtime_state=updated, now=NOW)
        assert updated_snapshot.state == MonitoringState.IDLE
        assert updated_snapshot.current_likelihood == 0.0
        assert updated_snapshot.queue_band == QueueBand.SLOW
        # SLOW interval = 900s, jitter ±15% = ±135s → range [765, 1035]
        assert updated.next_check_at is not None
        assert NOW + timedelta(seconds=760) <= updated.next_check_at <= NOW + timedelta(seconds=1040), (
            f"next_check_at {updated.next_check_at} outside SLOW range"
        )
        # last_live_at is preserved (not bumped) for offline resolve
        assert updated.last_live_at == stale.last_live_at
    def test_offline_resolve_with_favorite_target(
        self, cycle,
    ) -> None:
        """Favourite targets get at least MEDIUM band even after offline
        resolve — the favourite floor prevents demotion to SLOW."""
        stale = _runtime_state(
            stream_target_id="t1",
            previous_likelihood=0.5,
            next_check_at=NOW + timedelta(seconds=300),
        )

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            updated = self._apply(cycle, stale, is_live=False, is_favorite=True)

        updated_snapshot = cycle._build_snapshot(
            _target(id="t1", favorite=True), runtime_state=updated, now=NOW,
        )
        assert updated_snapshot.state == MonitoringState.IDLE
        assert updated_snapshot.current_likelihood == 0.0
        # Favourite floor → at least MEDIUM, never SLOW
        assert updated_snapshot.queue_band in (QueueBand.MEDIUM, QueueBand.FAST), (
            f"Expected at least MEDIUM for favourite, got {updated_snapshot.queue_band}"
        )


# ======================================================================
# Lifecycle — threading
# ======================================================================


class TestCycleLifecycle:
    def test_start_spawns_background_thread(self, cycle) -> None:
        cycle.start()
        assert cycle.is_running
        assert cycle._thread is not None
        assert cycle._thread.daemon is True
        assert cycle._thread.name == "monitoring-cycle"
        cycle.stop()

    def test_stop_joins_thread(self, cycle) -> None:
        cycle.start()
        cycle.stop()
        assert not cycle.is_running

    def test_start_is_idempotent(self, cycle, caplog) -> None:
        caplog.set_level(logging.WARNING)
        cycle.start()
        cycle.start()  # Second start — should warn and be no-op
        assert "already running" in caplog.text
        cycle.stop()

    def test_loop_uses_stop_event(self, cycle, mock_repos) -> None:
        """The loop respects the stop event between cycles."""
        mock_repos["target_repo"].list_all.return_value = []
        cycle.start()
        cycle.stop()
        # After stop, no more cycles run
        call_count_before = mock_repos["target_repo"].list_all.call_count
        threading.Event().wait(timeout=0.1)
        call_count_after = mock_repos["target_repo"].list_all.call_count
        assert call_count_after == call_count_before


# ======================================================================
# Configurability
# ======================================================================


class TestCycleConfig:
    def test_custom_loop_interval(
        self, logger, mock_repos, mock_engine, mock_queue_planner, result_store,
    ) -> None:
        """Custom loop_interval_seconds is used for the sleep between cycles."""
        c = MonitoringCycle(
            prediction_engine=mock_engine,
            stream_target_repo=mock_repos["target_repo"],
            recording_session_repo=mock_repos["session_repo"],
            result_store=result_store,
            queue_planner=mock_queue_planner,
            logger=logger,
            loop_interval_seconds=42,
            period_days=30.0,
        )
        assert c._loop_interval == 42

    def test_custom_period_days(
        self, logger, mock_repos, mock_engine, mock_queue_planner, result_store,
    ) -> None:
        """Custom period_days is passed through to prediction context."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        c = MonitoringCycle(
            prediction_engine=mock_engine,
            stream_target_repo=mock_repos["target_repo"],
            recording_session_repo=mock_repos["session_repo"],
            result_store=result_store,
            queue_planner=mock_queue_planner,
            logger=logger,
            loop_interval_seconds=3600,
            period_days=60.0,
        )
        c._runtime_states["t1"] = _runtime_state(stream_target_id="t1")
        mock_repos["session_repo"].list_by_target.return_value = []
        mock_engine.predict.return_value = _result()

        c._run_one_cycle()
        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs["period_days"] == 60.0
