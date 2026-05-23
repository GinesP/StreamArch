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
        snap = _snapshot(
            stream_target_id=target_id,
            next_check_at=next_check_at,
        )
        cycle._snapshots[target_id] = snap

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = return_result or _result()
        mock_engine.predict.return_value = result

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=now,
        ):
            cycle._run_one_cycle()
        return snap

    def test_processes_enabled_target(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Enabled target with snapshot — predicts and updates in-memory."""
        self.process_target(cycle, mock_repos, mock_engine, mock_queue_planner)

        # Prediction was called
        mock_engine.predict.assert_called_once()
        # In-memory snapshot was updated
        updated = cycle._snapshots.get("t1")
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

    def test_prediction_uses_current_snapshot(
        self, cycle, mock_repos, mock_engine, mock_queue_planner
    ) -> None:
        """Prediction uses the in-memory snapshot as loaded."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        initial_snap = _snapshot(stream_target_id="t1")
        cycle._snapshots["t1"] = initial_snap

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result(likelihood=0.3, confidence=Confidence.LOW)
        mock_engine.predict.return_value = result

        cycle._run_one_cycle()

        # Prediction used the initial snapshot
        predict_call = mock_engine.predict.call_args
        assert predict_call is not None
        assert predict_call.kwargs["snapshot"] is initial_snap

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
        snap = cycle._snapshots.get("new_target")
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

        snap = _snapshot(stream_target_id="t1", next_check_at=None)
        cycle._snapshots["t1"] = snap

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

        snap = cycle._snapshots.get("t1")
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

        snap = _snapshot(stream_target_id="t1")
        cycle._snapshots["t1"] = snap

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

        snap = _snapshot(stream_target_id="t1", current_likelihood=0.77)
        cycle._snapshots["t1"] = snap

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
        cycle._snapshots["t1"] = _snapshot(
            stream_target_id="t1", next_check_at=NOW + timedelta(hours=1),
        )
        cycle._snapshots["t2"] = _snapshot(
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
        c._snapshots["t1"] = _snapshot(stream_target_id="t1")
        mock_repos["session_repo"].list_by_target.return_value = []
        mock_engine.predict.return_value = _result()

        c._run_one_cycle()
        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs["period_days"] == 60.0
