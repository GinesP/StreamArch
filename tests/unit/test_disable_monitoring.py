"""Tests for DisableMonitoringHandler."""

import pytest

from app.application.commands.disable_monitoring import (
    DisableMonitoringCommand,
    DisableMonitoringHandler,
)
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence, Platform, QueueBand, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


def _insert_target(repo: StreamTargetRepository, **overrides) -> str:
    now = utc_now()
    target = StreamTarget(
        id=overrides.get("id", "test-id"),
        platform=overrides.get("platform", Platform.TWITCH),
        handle=overrides.get("handle", "streamer"),
        source_url=overrides.get("source_url", "https://twitch.tv/streamer"),
        display_name=overrides.get("display_name", "Streamer"),
        enabled=overrides.get("enabled", True),
        favorite=overrides.get("favorite", False),
        preferred_quality=overrides.get("preferred_quality", None),
        output_profile_id=overrides.get("output_profile_id", None),
        schedule_mode=overrides.get("schedule_mode", ScheduleMode.NONE),
        created_at=overrides.get("created_at", now),
        updated_at=overrides.get("updated_at", now),
    )
    repo.save(target)
    return target.id


def _insert_snapshot(
    repo: MonitoringSnapshotRepository,
    **overrides,
) -> None:
    now = utc_now()
    snapshot = MonitoringSnapshot(
        stream_target_id=overrides["stream_target_id"],
        state=overrides.get("state", MonitoringState.IDLE),
        queue_band=overrides.get("queue_band", None),
        current_likelihood=overrides.get("current_likelihood", 0.5),
        current_confidence=overrides.get("current_confidence", Confidence.MEDIUM),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", None),
        current_recording_session_id=overrides.get("current_recording_session_id", None),
        last_error_code=overrides.get("last_error_code", None),
        last_error_message=overrides.get("last_error_message", None),
        updated_at=overrides.get("updated_at", now),
    )
    repo.save(snapshot)


@pytest.fixture
def db_path(tmp_path) -> str:
    path = tmp_path / "test.db"
    conn = get_connection(path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return str(path)


@pytest.fixture
def target_repo(db_path) -> StreamTargetRepository:
    return StreamTargetRepository(db_path)


@pytest.fixture
def snapshot_repo(db_path) -> MonitoringSnapshotRepository:
    return MonitoringSnapshotRepository(db_path)


@pytest.fixture
def handler(
    target_repo: StreamTargetRepository,
    snapshot_repo: MonitoringSnapshotRepository,
) -> DisableMonitoringHandler:
    return DisableMonitoringHandler(
        stream_target_repo=target_repo,
        monitoring_snapshot_repo=snapshot_repo,
    )


class TestDisableMonitoringHandler:
    def test_disables_enabled_target(self, handler) -> None:
        target_repo = handler._target_repo
        tid = _insert_target(target_repo, id="t1", enabled=True)

        handler.handle(DisableMonitoringCommand(stream_id=tid))
        updated = target_repo.get(tid)

        assert updated is not None
        assert updated.enabled is False

    def test_resets_snapshot_to_idle(self, handler) -> None:
        target_repo = handler._target_repo
        snapshot_repo = handler._snapshot_repo
        tid = _insert_target(target_repo, id="t2", enabled=True)
        _insert_snapshot(
            snapshot_repo,
            stream_target_id=tid,
            state=MonitoringState.CHECKING,
            queue_band=QueueBand.FAST,
            current_likelihood=0.8,
        )
        handler.handle(DisableMonitoringCommand(stream_id=tid))
        snapshot = snapshot_repo.get(tid)

        assert snapshot is not None
        assert snapshot.state == MonitoringState.IDLE
        assert snapshot.queue_band is None
        # Prediction data is preserved (reset is about scheduling state).
        assert snapshot.current_likelihood == 0.8

    def test_resets_recording_snapshot_to_idle(self, handler) -> None:
        target_repo = handler._target_repo
        snapshot_repo = handler._snapshot_repo
        tid = _insert_target(target_repo, id="t3", enabled=True)
        _insert_snapshot(
            snapshot_repo,
            stream_target_id=tid,
            state=MonitoringState.RECORDING,
            queue_band=QueueBand.FAST,
        )

        handler.handle(DisableMonitoringCommand(stream_id=tid))
        snapshot = snapshot_repo.get(tid)

        assert snapshot.state == MonitoringState.IDLE
        assert snapshot.queue_band is None

    def test_idempotent_when_already_disabled(self, handler) -> None:
        target_repo = handler._target_repo
        snapshot_repo = handler._snapshot_repo
        tid = _insert_target(target_repo, id="t4", enabled=False)
        _insert_snapshot(
            snapshot_repo,
            stream_target_id=tid,
            state=MonitoringState.IDLE,
            queue_band=None,
        )

        # Capture snapshot timestamp before the no-op call.
        before = snapshot_repo.get(tid).updated_at

        handler.handle(DisableMonitoringCommand(stream_id="t4"))

        updated = target_repo.get("t4")
        assert updated is not None
        assert updated.enabled is False  # Still disabled
        # Snapshot was not touched.
        assert snapshot_repo.get(tid).updated_at == before

    def test_raises_on_missing_target(self, handler) -> None:
        cmd = DisableMonitoringCommand(stream_id="nonexistent")
        with pytest.raises(ValueError, match="not found"):
            handler.handle(cmd)

    def test_updates_updated_at_timestamp(self, handler) -> None:
        target_repo = handler._target_repo
        tid = _insert_target(target_repo, id="t5", enabled=True)
        before = target_repo.get(tid).updated_at

        handler.handle(DisableMonitoringCommand(stream_id=tid))
        after = target_repo.get(tid).updated_at

        assert after > before
