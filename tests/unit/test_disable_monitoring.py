"""Tests for DisableMonitoringHandler."""

import pytest

from app.application.commands.disable_monitoring import (
    DisableMonitoringCommand,
    DisableMonitoringHandler,
)
from app.domain.shared.types import Platform, utc_now
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
def handler(target_repo) -> DisableMonitoringHandler:
    return DisableMonitoringHandler(
        stream_target_repo=target_repo,
    )


class TestDisableMonitoringHandler:
    def test_disables_enabled_target(self, handler) -> None:
        target_repo = handler._target_repo
        tid = _insert_target(target_repo, id="t1", enabled=True)

        handler.handle(DisableMonitoringCommand(stream_id=tid))
        updated = target_repo.get(tid)

        assert updated is not None
        assert updated.enabled is False

    def test_idempotent_when_already_disabled(self, handler) -> None:
        target_repo = handler._target_repo
        tid = _insert_target(target_repo, id="t2", enabled=False)

        before = target_repo.get(tid).updated_at
        handler.handle(DisableMonitoringCommand(stream_id=tid))

        updated = target_repo.get(tid)
        assert updated is not None
        assert updated.enabled is False
        # Target was not modified (idempotent).
        assert target_repo.get(tid).updated_at == before

    def test_raises_on_missing_target(self, handler) -> None:
        cmd = DisableMonitoringCommand(stream_id="nonexistent")
        with pytest.raises(ValueError, match="not found"):
            handler.handle(cmd)

    def test_updates_updated_at_timestamp(self, handler) -> None:
        target_repo = handler._target_repo
        tid = _insert_target(target_repo, id="t3", enabled=True)
        before = target_repo.get(tid).updated_at

        handler.handle(DisableMonitoringCommand(stream_id=tid))
        after = target_repo.get(tid).updated_at

        assert after > before
