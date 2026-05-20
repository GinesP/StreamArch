"""Tests for ListRecordingsHandler."""

import pytest

from app.application.dto.recordings import RecordingSessionDTO
from app.application.queries.list_recordings import ListRecordingsHandler, ListRecordingsQuery
from app.domain.recording.session import RecordingSession
from app.domain.shared.types import Platform, QueueBand, RecordingStatus, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


def _insert_target(repo: StreamTargetRepository, target_id: str) -> str:
    now = utc_now()
    target = StreamTarget(
        id=target_id,
        platform=Platform.TWITCH,
        handle="streamer",
        source_url="https://twitch.tv/streamer",
        display_name="Streamer",
        enabled=True,
        favorite=False,
        preferred_quality=None,
        output_profile_id=None,
        schedule_mode=ScheduleMode.NONE,
        created_at=now,
        updated_at=now,
    )
    repo.save(target)
    return target.id


def _insert_session(
    repo: RecordingSessionRepository, target_repo: StreamTargetRepository | None = None, **overrides
) -> str:
    now = utc_now()
    stream_target_id = overrides.get("stream_target_id", "target-1")

    # Ensure the referenced stream target exists in the database
    if target_repo is not None and target_repo.get(stream_target_id) is None:
        _insert_target(target_repo, stream_target_id)

    status = overrides.get("status", RecordingStatus.COMPLETED)
    ended_at = overrides.get("ended_at", ...)

    # Terminal sessions must have an ended_at — default to now if not provided
    is_terminal = status in (
        RecordingStatus.COMPLETED,
        RecordingStatus.FAILED,
        RecordingStatus.ABORTED,
        RecordingStatus.SPLIT,
    )
    if ended_at is ... and is_terminal:
        ended_at = now
    elif ended_at is ...:
        ended_at = None

    session = RecordingSession(
        id=overrides.get("id", f"session-{len(overrides)}"),
        stream_target_id=stream_target_id,
        started_at=overrides.get("started_at", now),
        ended_at=ended_at,
        status=status,
        source_platform=overrides.get("source_platform", Platform.TWITCH),
        stream_title=overrides.get("stream_title", None),
        detected_by_queue=overrides.get("detected_by_queue", QueueBand.FAST),
        detection_latency_seconds=overrides.get("detection_latency_seconds", 12.5),
        scheduled_hint_delay_minutes=overrides.get("scheduled_hint_delay_minutes", None),
        split_reason=overrides.get("split_reason", None),
        error_code=overrides.get("error_code", None),
        error_message=overrides.get("error_message", None),
        created_at=overrides.get("created_at", now),
        updated_at=overrides.get("updated_at", now),
    )
    repo.save(session)
    return session.id


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
def recording_repo(db_path) -> RecordingSessionRepository:
    return RecordingSessionRepository(db_path)


@pytest.fixture
def handler(recording_repo) -> ListRecordingsHandler:
    return ListRecordingsHandler(
        recording_session_repo=recording_repo,
    )


class TestListRecordingsHandler:
    def test_returns_empty_list_when_no_sessions(self, handler) -> None:
        result = handler.handle(ListRecordingsQuery())
        assert result == []

    def test_returns_all_sessions(
        self, handler, recording_repo, target_repo
    ) -> None:
        _insert_session(recording_repo, target_repo, id="s1", stream_target_id="t1")
        _insert_session(recording_repo, target_repo, id="s2", stream_target_id="t2")
        _insert_session(recording_repo, target_repo, id="s3", stream_target_id="t1")

        result = handler.handle(ListRecordingsQuery())
        assert len(result) == 3

    def test_filters_by_stream_target(
        self, handler, recording_repo, target_repo
    ) -> None:
        _insert_session(recording_repo, target_repo, id="s1", stream_target_id="t1")
        _insert_session(recording_repo, target_repo, id="s2", stream_target_id="t2")
        _insert_session(recording_repo, target_repo, id="s3", stream_target_id="t1")

        result = handler.handle(ListRecordingsQuery(stream_id="t1"))
        assert len(result) == 2
        assert all(dto.stream_target_id == "t1" for dto in result)

    def test_returns_empty_when_stream_id_has_no_sessions(
        self, handler, recording_repo, target_repo
    ) -> None:
        _insert_session(recording_repo, target_repo, id="s1", stream_target_id="t1")

        result = handler.handle(ListRecordingsQuery(stream_id="nonexistent"))
        assert result == []

    def test_dto_contains_serialized_fields(
        self, handler, recording_repo, target_repo
    ) -> None:
        _insert_session(
            recording_repo,
            target_repo,
            id="dto-test",
            stream_target_id="t1",
            stream_title="My Stream",
            status=RecordingStatus.RECORDING,
            source_platform=Platform.YOUTUBE,
            error_code="ERR_01",
            error_message="Something went wrong",
        )

        result = handler.handle(ListRecordingsQuery())
        assert len(result) == 1
        dto = result[0]

        assert isinstance(dto, RecordingSessionDTO)
        assert dto.id == "dto-test"
        assert dto.stream_target_id == "t1"
        assert dto.status == "recording"
        assert dto.source_platform == "youtube"
        assert dto.stream_title == "My Stream"
        assert dto.error_code == "ERR_01"
        assert dto.error_message == "Something went wrong"
        assert dto.detected_by_queue == "fast"

    def test_returns_newest_first(
        self, handler, recording_repo, target_repo
    ) -> None:
        now = utc_now()
        earlier = now.replace(year=2024)
        later = now.replace(year=2025)

        _insert_session(recording_repo, target_repo, id="old", started_at=earlier)
        _insert_session(recording_repo, target_repo, id="new", started_at=later)

        result = handler.handle(ListRecordingsQuery())
        assert result[0].id == "new"
        assert result[1].id == "old"

    def test_ended_at_and_duration_are_none_when_active(
        self, handler, recording_repo, target_repo
    ) -> None:
        _insert_session(
            recording_repo,
            target_repo,
            id="active-session",
            status=RecordingStatus.RECORDING,
        )

        result = handler.handle(ListRecordingsQuery())
        dto = result[0]
        assert dto.ended_at is None
        assert dto.duration_seconds is None

    def test_duration_computed_for_finished_session(
        self, handler, recording_repo, target_repo
    ) -> None:
        now = utc_now()
        start = now.replace(hour=10, minute=0, second=0)
        end = now.replace(hour=10, minute=30, second=0)

        _insert_session(
            recording_repo,
            target_repo,
            id="finished-session",
            status=RecordingStatus.COMPLETED,
            started_at=start,
            ended_at=end,
        )

        result = handler.handle(ListRecordingsQuery())
        dto = result[0]
        assert dto.duration_seconds == 1800.0  # 30 minutes
