"""Tests for MarkFavoriteHandler."""

import pytest

from app.application.commands.mark_favorite import (
    MarkFavoriteCommand,
    MarkFavoriteHandler,
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
def repo(db_path) -> StreamTargetRepository:
    return StreamTargetRepository(db_path)


@pytest.fixture
def handler(repo: StreamTargetRepository) -> MarkFavoriteHandler:
    return MarkFavoriteHandler(stream_target_repo=repo)


class TestMarkFavoriteHandler:
    def test_marks_non_favorite_as_favorite(self, handler, repo) -> None:
        tid = _insert_target(repo, id="t1", favorite=False)

        handler.handle(MarkFavoriteCommand(stream_id="t1"))
        updated = repo.get("t1")

        assert updated is not None
        assert updated.favorite is True

    def test_idempotent_when_already_favorite(self, handler, repo) -> None:
        tid = _insert_target(repo, id="t2", favorite=True)
        before = repo.get(tid).updated_at

        handler.handle(MarkFavoriteCommand(stream_id="t2"))
        after = repo.get(tid).updated_at

        assert repo.get(tid).favorite is True
        assert after == before  # No update performed

    def test_raises_on_missing_target(self, handler) -> None:
        cmd = MarkFavoriteCommand(stream_id="nonexistent")
        with pytest.raises(ValueError, match="not found"):
            handler.handle(cmd)

    def test_updates_updated_at_timestamp(self, handler, repo) -> None:
        tid = _insert_target(repo, id="t3", favorite=False)
        before = repo.get(tid).updated_at

        handler.handle(MarkFavoriteCommand(stream_id="t3"))
        after = repo.get(tid).updated_at

        assert after > before
