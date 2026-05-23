"""Tests for ListStreamsHandler."""

from unittest.mock import MagicMock

import pytest

from app.application.dto.streams import StreamOverviewDTO
from app.application.queries.list_streams import ListStreamsHandler, ListStreamsQuery
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
def handler(target_repo) -> ListStreamsHandler:
    monitoring_cycle = MagicMock()
    monitoring_cycle.get_all_snapshots.return_value = []
    return ListStreamsHandler(
        stream_target_repo=target_repo,
        monitoring_cycle=monitoring_cycle,
    )


class TestListStreamsHandler:
    def test_returns_empty_list_when_no_targets(self, handler) -> None:
        result = handler.handle(ListStreamsQuery())
        assert result == []

    def test_returns_all_targets(self, handler, target_repo) -> None:
        _insert_target(target_repo, id="t1", handle="alpha", display_name="Alpha")
        _insert_target(target_repo, id="t2", handle="beta", display_name="Beta")
        _insert_target(target_repo, id="t3", handle="gamma", display_name="Gamma")

        result = handler.handle(ListStreamsQuery())
        assert len(result) == 3

    def test_merges_snapshot_state(self, handler, target_repo) -> None:
        tid = _insert_target(target_repo, id="t1", handle="live_streamer")
        handler._monitoring_cycle.get_all_snapshots.return_value = [
            _make_snapshot(
                stream_target_id=tid,
                state=MonitoringState.RECORDING,
                current_likelihood=0.95,
                current_confidence=Confidence.HIGH,
            ),
        ]

        result = handler.handle(ListStreamsQuery())
        assert len(result) == 1
        dto = result[0]
        assert dto.state == "recording"
        assert dto.current_likelihood == 0.95
        assert dto.current_confidence == "high"

    def test_returns_unknown_state_when_no_snapshot(self, handler, target_repo) -> None:
        _insert_target(target_repo, id="t1", handle="new_streamer")

        result = handler.handle(ListStreamsQuery())
        assert result[0].state == "unknown"
        assert result[0].current_likelihood == 0.0
        assert result[0].current_confidence == "low"

    def test_preserves_target_fields(self, handler, target_repo) -> None:
        tid = _insert_target(
            target_repo,
            id="t1",
            handle="my_handle",
            display_name="My Streamer",
            platform=Platform.YOUTUBE,
            enabled=True,
            favorite=True,
            source_url="https://youtube.com/@my_handle",
        )
        handler._monitoring_cycle.get_all_snapshots.return_value = [
            _make_snapshot(stream_target_id=tid),
        ]

        dto = handler.handle(ListStreamsQuery())[0]
        assert dto.id == "t1"
        assert dto.handle == "my_handle"
        assert dto.display_name == "My Streamer"
        assert dto.platform == "youtube"
        assert dto.enabled is True
        assert dto.favorite is True
