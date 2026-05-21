"""Tests for MonitoringCycle — orchestrator that runs in a background
thread, periodically checking all enabled stream targets.

All external dependencies (repositories, prediction engine, live check
service) are mocked so these tests are fast, deterministic, and isolated.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.application.orchestrators.monitoring_cycle import MonitoringCycle
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
    """Return a default PredictionResult with configurable overrides."""
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
    """Return fresh MagicMock instances for all three repositories."""
    return {
        "target_repo": MagicMock(),
        "snapshot_repo": MagicMock(),
        "session_repo": MagicMock(),
    }


@pytest.fixture
def mock_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_live_check() -> MagicMock:
    return MagicMock()


@pytest.fixture
def cycle(
    mock_engine: MagicMock,
    mock_live_check: MagicMock,
    mock_repos: dict,
    logger: logging.Logger,
) -> MonitoringCycle:
    """Return a MonitoringCycle with all dependencies mocked.

    The cycle is **not started** — call ``cycle.start()`` explicitly
    or invoke ``_run_one_cycle()`` directly in tests.
    """
    return MonitoringCycle(
        prediction_engine=mock_engine,
        live_check_service=mock_live_check,
        stream_target_repo=mock_repos["target_repo"],
        monitoring_snapshot_repo=mock_repos["snapshot_repo"],
        recording_session_repo=mock_repos["session_repo"],
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
        mock_repos["snapshot_repo"].get.assert_not_called()
        mock_repos["session_repo"].list_by_target.assert_not_called()

    def test_skips_disabled_targets(self, cycle, mock_repos, caplog) -> None:
        caplog.set_level(logging.DEBUG)
        t1 = _target(id="t1", enabled=False)
        t2 = _target(id="t2", enabled=False)
        mock_repos["target_repo"].list_all.return_value = [t1, t2]

        cycle._run_one_cycle()

        assert "no enabled targets" in caplog.text
        mock_repos["snapshot_repo"].get.assert_not_called()


class TestCycleSingleTarget:
    """Happy path — one enabled target with an existing snapshot."""

    def process_target(
        self,
        cycle,
        mock_repos,
        mock_engine,
        mock_live_check,
        target_id="t1",
        next_check_at=None,
        return_result=None,
        now=NOW,
    ) -> None:
        """Helper: run one cycle with a single enabled target.

        *now* is injected as the fixed current time so time-based
        assertions (``next_check_at <= now``) are deterministic.
        """
        target = _target(id=target_id)
        mock_repos["target_repo"].list_all.return_value = [target]

        snap = _snapshot(
            stream_target_id=target_id,
            next_check_at=next_check_at,
        )
        mock_repos["snapshot_repo"].get.return_value = snap

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

    def test_processes_enabled_target(self, cycle, mock_repos, mock_engine, mock_live_check) -> None:
        """Enabled target with snapshot — predicts and saves."""
        self.process_target(cycle, mock_repos, mock_engine, mock_live_check)

        # Prediction was called
        mock_engine.predict.assert_called_once()
        # Snapshot was saved
        mock_repos["snapshot_repo"].save.assert_called_once()
        # Live check triggered (no next_check_at)
        mock_live_check.check_stream.assert_called_once_with("t1")

    def test_triggers_check_when_next_check_at_is_none(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """No next_check_at → live check is triggered."""
        self.process_target(
            cycle, mock_repos, mock_engine, mock_live_check,
            next_check_at=None,
        )
        mock_live_check.check_stream.assert_called_once_with("t1")

    def test_triggers_check_when_next_check_at_is_past(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """next_check_at in the past → live check is triggered."""
        self.process_target(
            cycle, mock_repos, mock_engine, mock_live_check,
            next_check_at=NOW - timedelta(seconds=10),
        )
        mock_live_check.check_stream.assert_called_once_with("t1")

    def test_skips_check_when_next_check_at_is_future(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """next_check_at in the future → no live check."""
        self.process_target(
            cycle, mock_repos, mock_engine, mock_live_check,
            next_check_at=NOW + timedelta(seconds=300),
        )
        mock_live_check.check_stream.assert_not_called()

    def test_re_reads_snapshot_after_check(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """After check_stream is called, the snapshot is re-read from the repo."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        initial_snap = _snapshot(stream_target_id="t1")
        mock_repos["snapshot_repo"].get.return_value = initial_snap

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        # After check_stream, the repo returns an updated snapshot
        updated_snap = _snapshot(
            stream_target_id="t1",
            state=MonitoringState.IDLE,
            current_likelihood=0.0,
            last_checked_at=NOW,
        )

        def get_side_effect(stream_id):
            if stream_id == "t1":
                return updated_snap
            return None

        mock_repos["snapshot_repo"].get.side_effect = [initial_snap, updated_snap]

        result = _result(likelihood=0.3, confidence=Confidence.LOW)
        mock_engine.predict.return_value = result

        cycle._run_one_cycle()

        # Prediction used the *updated* snapshot
        predict_call = mock_engine.predict.call_args
        assert predict_call is not None
        # The snapshot passed to predict should be the one after check
        assert predict_call.kwargs["snapshot"] is updated_snap

    def test_creates_snapshot_for_new_target(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """Target with no existing snapshot gets a default before processing."""
        target = _target(id="new_target")
        mock_repos["target_repo"].list_all.return_value = [target]
        mock_repos["snapshot_repo"].get.return_value = None  # No snapshot

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result(likelihood=0.3, confidence=Confidence.LOW)
        mock_engine.predict.return_value = result

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        # Live check was triggered (no next_check_at)
        mock_live_check.check_stream.assert_called_once_with("new_target")

        # A snapshot was saved — verify key fields
        saved = mock_repos["snapshot_repo"].save.call_args[0][0]
        assert saved.stream_target_id == "new_target"
        assert saved.current_likelihood == 0.3
        assert saved.current_confidence == Confidence.LOW

    def test_prediction_data_flows_to_snapshot(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """Prediction engine output is correctly mapped to the saved snapshot."""
        target = _target(id="t1", favorite=True)
        mock_repos["target_repo"].list_all.return_value = [target]

        snap = _snapshot(stream_target_id="t1", next_check_at=None)
        mock_repos["snapshot_repo"].get.return_value = snap

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

        saved = mock_repos["snapshot_repo"].save.call_args[0][0]
        assert saved.current_likelihood == 0.85
        assert saved.current_confidence == Confidence.HIGH
        # Time-based assertions: next_check_at should be NOW + jittered interval
        assert saved.next_check_at is not None
        assert saved.next_check_at > NOW
        # Favourite with high likelihood → FAST or MEDIUM band
        assert saved.queue_band in (QueueBand.FAST, QueueBand.MEDIUM)

    def test_provides_session_count_to_engine(
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """The number of recording sessions is passed to the prediction engine."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        snap = _snapshot(stream_target_id="t1")
        mock_repos["snapshot_repo"].get.return_value = snap

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
        self, cycle, mock_repos, mock_engine, mock_live_check
    ) -> None:
        """The snapshot's current_likelihood is passed as previous_priority."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]

        snap = _snapshot(stream_target_id="t1", current_likelihood=0.77)
        mock_repos["snapshot_repo"].get.return_value = snap

        sessions = []
        mock_repos["session_repo"].list_by_target.return_value = sessions

        result = _result()
        mock_engine.predict.return_value = result

        cycle._run_one_cycle()

        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs["previous_priority"] == 0.77

    def test_records_error_count(
        self, cycle, mock_repos, mock_engine, mock_live_check, caplog
    ) -> None:
        """When a target raises, the error is logged and cycle continues.

        t1 succeeds (predict returns normally).
        t2 fails because ``predict`` raises ``ValueError``.
        """
        caplog.set_level(logging.INFO)

        t1 = _target(id="t1")
        t2 = _target(id="t2")
        mock_repos["target_repo"].list_all.return_value = [t1, t2]

        # Both targets return valid snapshots from the repo.
        snap1 = _snapshot(stream_target_id="t1", next_check_at=NOW + timedelta(hours=1))
        snap2 = _snapshot(stream_target_id="t2", next_check_at=NOW + timedelta(hours=1))
        mock_repos["snapshot_repo"].get.side_effect = [snap1, snap2]

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
        # No new calls after stop
        assert call_count_after == call_count_before


# ======================================================================
# Configurability
# ======================================================================


class TestCycleConfig:
    def test_custom_loop_interval(self, logger, mock_repos, mock_engine, mock_live_check) -> None:
        """Custom loop_interval_seconds is used for the sleep between cycles."""
        c = MonitoringCycle(
            prediction_engine=mock_engine,
            live_check_service=mock_live_check,
            stream_target_repo=mock_repos["target_repo"],
            monitoring_snapshot_repo=mock_repos["snapshot_repo"],
            recording_session_repo=mock_repos["session_repo"],
            logger=logger,
            loop_interval_seconds=42,
            period_days=30.0,
        )
        assert c._loop_interval == 42

    def test_custom_period_days(self, logger, mock_repos, mock_engine, mock_live_check) -> None:
        """Custom period_days is passed through to prediction context."""
        target = _target(id="t1")
        mock_repos["target_repo"].list_all.return_value = [target]
        mock_repos["snapshot_repo"].get.return_value = _snapshot(stream_target_id="t1")
        mock_repos["session_repo"].list_by_target.return_value = []
        mock_engine.predict.return_value = _result()

        c = MonitoringCycle(
            prediction_engine=mock_engine,
            live_check_service=mock_live_check,
            stream_target_repo=mock_repos["target_repo"],
            monitoring_snapshot_repo=mock_repos["snapshot_repo"],
            recording_session_repo=mock_repos["session_repo"],
            logger=logger,
            loop_interval_seconds=3600,
            period_days=60.0,
        )

        c._run_one_cycle()
        call_kwargs = mock_engine.predict.call_args.kwargs
        assert call_kwargs["period_days"] == 60.0
