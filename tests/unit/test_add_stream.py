"""Tests for AddStreamHandler."""

import pytest

from app.application.commands.add_stream import (
    AddStreamCommand,
    AddStreamHandler,
)
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
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
def handler(db_path) -> AddStreamHandler:
    return AddStreamHandler(
        stream_target_repo=StreamTargetRepository(db_path),
        monitoring_snapshot_repo=MonitoringSnapshotRepository(db_path),
    )


class TestAddStreamHandler:
    def test_creates_target_and_snapshot(self, handler) -> None:
        cmd = AddStreamCommand(
            platform="twitch",
            handle="teststreamer",
            source_url="https://twitch.tv/teststreamer",
            display_name="Test Streamer",
        )

        target_id = handler.handle(cmd)

        # Stream target is persisted
        target = handler._target_repo.get(target_id)
        assert target is not None
        assert target.handle == "teststreamer"
        assert target.platform.value == "twitch"
        assert target.display_name == "Test Streamer"
        assert target.enabled is True
        assert target.favorite is False
        assert target.schedule_mode.value == "none"

        # Monitoring snapshot is persisted with IDLE state
        snapshot = handler._snapshot_repo.get(target_id)
        assert snapshot is not None
        assert snapshot.stream_target_id == target_id
        assert snapshot.state == MonitoringState.IDLE
        assert snapshot.current_likelihood == 0.0
        assert snapshot.current_confidence == Confidence.LOW

    def test_accepts_optional_fields(self, handler) -> None:
        cmd = AddStreamCommand(
            platform="youtube",
            handle="ytchannel",
            source_url="https://youtube.com/@ytchannel",
            display_name="YT Channel",
            preferred_quality="1080p60",
            output_profile_id="high_quality",
            schedule_mode="hinted",
        )

        target_id = handler.handle(cmd)
        target = handler._target_repo.get(target_id)

        assert target.preferred_quality == "1080p60"
        assert target.output_profile_id == "high_quality"
        assert target.schedule_mode.value == "hinted"

    def test_rejects_empty_handle(self, handler) -> None:
        cmd = AddStreamCommand(
            platform="twitch",
            handle="   ",
            source_url="https://twitch.tv/test",
            display_name="Test",
        )
        with pytest.raises(ValueError, match="handle must not be empty"):
            handler.handle(cmd)

    def test_rejects_invalid_platform(self, handler) -> None:
        cmd = AddStreamCommand(
            platform="unsupported",
            handle="test",
            source_url="https://twitch.tv/test",
            display_name="Test",
        )
        with pytest.raises(ValueError, match="Invalid platform"):
            handler.handle(cmd)

    def test_rejects_invalid_schedule_mode(self, handler) -> None:
        cmd = AddStreamCommand(
            platform="twitch",
            handle="test",
            source_url="https://twitch.tv/test",
            display_name="Test",
            schedule_mode="bogus",
        )
        with pytest.raises(ValueError, match="Invalid schedule_mode"):
            handler.handle(cmd)

    def test_returns_different_ids_each_time(self, handler) -> None:
        cmd1 = AddStreamCommand(
            platform="twitch", handle="a", source_url="https://a.tv", display_name="A"
        )
        cmd2 = AddStreamCommand(
            platform="youtube", handle="b", source_url="https://b.tv", display_name="B"
        )

        id1 = handler.handle(cmd1)
        id2 = handler.handle(cmd2)

        assert id1 != id2
