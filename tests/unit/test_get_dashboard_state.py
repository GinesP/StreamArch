"""Tests for GetDashboardStateHandler."""

from unittest.mock import MagicMock

import pytest

from app.application.queries.get_dashboard_state import (
    GetDashboardStateHandler,
    GetDashboardStateQuery,
)
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence, Platform, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


def _insert_target(repo: StreamTargetRepository, **overrides) -> str:
    now = utc_now()
    target = StreamTarget(
        id=overrides.get("id", f"target-{len(overrides)}"),
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


def _make_snapshot(**overrides) -> MonitoringSnapshot:
    """Build a MonitoringSnapshot for test setup."""
    now = utc_now()
    return MonitoringSnapshot(
        stream_target_id=overrides.get("stream_target_id", "unknown"),
        state=overrides.get("state", MonitoringState.IDLE),
        queue_band=overrides.get("queue_band", None),
        current_likelihood=overrides.get("current_likelihood", 0.0),
        current_confidence=overrides.get("current_confidence", Confidence.LOW),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", None),
        current_recording_session_id=overrides.get("current_recording_session_id", None),
        last_error_code=overrides.get("last_error_code", None),
        last_error_message=overrides.get("last_error_message", None),
        updated_at=overrides.get("updated_at", now),
    )


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
def handler(target_repo) -> GetDashboardStateHandler:
    monitoring_cycle = MagicMock()
    monitoring_cycle.get_all_snapshots.return_value = []
    return GetDashboardStateHandler(
        stream_target_repo=target_repo,
        monitoring_cycle=monitoring_cycle,
    )


class TestGetDashboardStateHandler:
    def test_returns_empty_state(self, handler) -> None:
        state = handler.handle(GetDashboardStateQuery())
        assert state.total_count == 0
        assert state.live_count == 0
        assert state.error_count == 0
        assert state.idle_count == 0
        assert state.streams == []

    def test_counts_live_streams(self, handler, target_repo) -> None:
        live_id = _insert_target(target_repo, id="live", handle="live_user")
        error_id = _insert_target(target_repo, id="err", handle="error_user")
        idle_id = _insert_target(target_repo, id="idle", handle="idle_user")

        handler._monitoring_cycle.get_all_snapshots.return_value = [
            _make_snapshot(stream_target_id=live_id, state=MonitoringState.RECORDING),
            _make_snapshot(stream_target_id=error_id, state=MonitoringState.ERROR),
            _make_snapshot(stream_target_id=idle_id, state=MonitoringState.IDLE),
        ]

        state = handler.handle(GetDashboardStateQuery())

        assert state.total_count == 3
        assert state.live_count == 1
        assert state.error_count == 1
        assert state.idle_count == 1

    def test_counts_all_non_recording_error_as_idle(self, handler, target_repo) -> None:
        t1 = _insert_target(target_repo, id="t1", handle="checking")
        t2 = _insert_target(target_repo, id="t2", handle="postproc")
        handler._monitoring_cycle.get_all_snapshots.return_value = [
            _make_snapshot(stream_target_id=t1, state=MonitoringState.CHECKING),
            _make_snapshot(stream_target_id=t2, state=MonitoringState.POST_PROCESSING),
        ]

        state = handler.handle(GetDashboardStateQuery())

        assert state.total_count == 2
        assert state.live_count == 0
        assert state.error_count == 0
        assert state.idle_count == 2  # CHECKING and POST_PROCESSING count as idle

    def test_classifies_no_snapshot_as_idle(self, handler, target_repo) -> None:
        _insert_target(target_repo, id="no-snap", handle="fresh")
        handler._monitoring_cycle.get_all_snapshots.return_value = []

        state = handler.handle(GetDashboardStateQuery())

        assert state.total_count == 1
        assert state.idle_count == 1
        assert state.streams[0].state == "unknown"

    def test_includes_stream_overviews(self, handler, target_repo) -> None:
        tid = _insert_target(
            target_repo,
            id="dash-test",
            handle="dashboard_user",
            display_name="Dashboard User",
        )
        handler._monitoring_cycle.get_all_snapshots.return_value = [
            _make_snapshot(
                stream_target_id=tid,
                state=MonitoringState.RECORDING,
                current_likelihood=0.88,
                current_confidence=Confidence.HIGH,
            ),
        ]

        state = handler.handle(GetDashboardStateQuery())
        dto = state.streams[0]

        assert dto.id == "dash-test"
        assert dto.handle == "dashboard_user"
        assert dto.display_name == "Dashboard User"
        assert dto.state == "recording"
        assert dto.current_likelihood == 0.88
        assert dto.current_confidence == "high"
