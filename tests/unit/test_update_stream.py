"""Tests for UpdateStreamHandler."""

import sqlite3
from datetime import timedelta

import pytest

from app.application.commands.update_stream import (
    UpdateStreamCommand,
    UpdateStreamHandler,
)
from app.domain.shared.types import Platform, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


def _insert_target(repo: StreamTargetRepository, **overrides) -> str:
    """Helper: insert a stream target and return its id."""
    now = utc_now()
    target = StreamTarget(
        id=overrides.get("id", "test-id-1"),
        platform=overrides.get("platform", Platform.TWITCH),
        handle=overrides.get("handle", "teststreamer"),
        source_url=overrides.get("source_url", "https://twitch.tv/teststreamer"),
        display_name=overrides.get("display_name", "Test Streamer"),
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


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    return conn


@pytest.fixture
def repo(db) -> StreamTargetRepository:
    return StreamTargetRepository(db)


@pytest.fixture
def handler(repo) -> UpdateStreamHandler:
    return UpdateStreamHandler(stream_target_repo=repo)


class TestUpdateStreamHandler:
    def test_updates_display_name(self, handler, repo) -> None:
        target_id = _insert_target(repo)

        handler.handle(UpdateStreamCommand(stream_id=target_id, display_name="New Name"))
        updated = repo.get(target_id)

        assert updated.display_name == "New Name"

    def test_updates_multiple_fields(self, handler, repo) -> None:
        target_id = _insert_target(repo)

        handler.handle(
            UpdateStreamCommand(
                stream_id=target_id,
                display_name="Updated",
                source_url="https://new.url/stream",
                enabled=False,
                favorite=True,
            )
        )
        updated = repo.get(target_id)

        assert updated.display_name == "Updated"
        assert updated.source_url == "https://new.url/stream"
        assert updated.enabled is False
        assert updated.favorite is True

    def test_updates_schedule_mode(self, handler, repo) -> None:
        target_id = _insert_target(repo)

        handler.handle(
            UpdateStreamCommand(stream_id=target_id, schedule_mode="hinted")
        )
        updated = repo.get(target_id)

        assert updated.schedule_mode == ScheduleMode.HINTED

    def test_updates_updated_at_timestamp(self, handler, repo) -> None:
        target_id = _insert_target(repo)
        before = repo.get(target_id).updated_at

        handler.handle(
            UpdateStreamCommand(stream_id=target_id, display_name="Renamed")
        )
        after = repo.get(target_id).updated_at

        assert after > before

    def test_raises_on_unknown_target(self, handler, repo) -> None:
        cmd = UpdateStreamCommand(stream_id="nonexistent", display_name="X")
        with pytest.raises(ValueError, match="not found"):
            handler.handle(cmd)

    def test_raises_on_unknown_field(self, handler, repo) -> None:
        target_id = _insert_target(repo)

        cmd = UpdateStreamCommand(stream_id=target_id, nonexistent_field="x")
        with pytest.raises(ValueError, match="non-updatable"):
            handler.handle(cmd)

    def test_raises_on_immutable_id_field(self, handler, repo) -> None:
        target_id = _insert_target(repo)

        cmd = UpdateStreamCommand(stream_id=target_id, id="new-id")
        with pytest.raises(ValueError, match="non-updatable"):
            handler.handle(cmd)

    def test_allows_clearing_optional_fields(self, handler, repo) -> None:
        target_id = _insert_target(
            repo,
            preferred_quality="1080p60",
            output_profile_id="high",
        )

        handler.handle(
            UpdateStreamCommand(
                stream_id=target_id,
                preferred_quality=None,
                output_profile_id=None,
            )
        )
        updated = repo.get(target_id)

        assert updated.preferred_quality is None
        assert updated.output_profile_id is None
