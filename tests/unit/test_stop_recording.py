"""Tests for StopRecordingHandler.

Verifies the command handler correctly:
- Delegates to RecordingService for active sessions.
- Short-circuits for already-finished sessions (idempotent).
- Raises ValueError for nonexistent sessions.

Uses a real SQLite database (temp file) for the session repository
and a mocked RecordingService.
"""

from unittest.mock import MagicMock

import pytest

from app.application.commands.stop_recording import (
    StopRecordingCommand,
    StopRecordingHandler,
)
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


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path) -> str:
    """Create a temp database with schema applied."""
    path = tmp_path / "test.db"
    conn = get_connection(path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return str(path)


@pytest.fixture
def session_repo(db_path) -> RecordingSessionRepository:
    return RecordingSessionRepository(db_path)


@pytest.fixture
def target_repo(db_path) -> StreamTargetRepository:
    return StreamTargetRepository(db_path)


@pytest.fixture
def recording_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def handler(
    session_repo: RecordingSessionRepository,
    recording_service: MagicMock,
) -> StopRecordingHandler:
    return StopRecordingHandler(
        recording_session_repo=session_repo,
        recording_service=recording_service,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _insert_target(repo: StreamTargetRepository, target_id: str) -> str:
    """Insert a StreamTarget into the repo and return its id."""
    now = utc_now()
    target = StreamTarget(
        id=target_id,
        platform=Platform.TWITCH,
        handle=target_id,
        source_url="https://example.com",
        display_name=f"Target {target_id}",
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
    repo: RecordingSessionRepository,
    target_repo: StreamTargetRepository | None = None,
    **overrides,
) -> str:
    """Insert a RecordingSession, creating a target if needed."""
    now = utc_now()
    stream_target_id = overrides.get("stream_target_id", "target-1")

    # Ensure the referenced stream target exists (FK constraint)
    if target_repo is not None and target_repo.get(stream_target_id) is None:
        _insert_target(target_repo, stream_target_id)

    status = overrides.get("status", RecordingStatus.COMPLETED)
    is_terminal = status in (
        RecordingStatus.COMPLETED,
        RecordingStatus.FAILED,
        RecordingStatus.ABORTED,
        RecordingStatus.SPLIT,
    )

    ended_at = overrides.get("ended_at", ...)
    if ended_at is ... and is_terminal:
        ended_at = now
    elif ended_at is ...:
        ended_at = None

    session = RecordingSession(
        id=overrides.get("id", "test-session"),
        stream_target_id=stream_target_id,
        started_at=overrides.get("started_at", now),
        ended_at=ended_at,
        status=status,
        source_platform=overrides.get("source_platform", Platform.TWITCH),
        stream_title=overrides.get("stream_title", None),
        detected_by_queue=overrides.get("detected_by_queue", QueueBand.FAST),
        detection_latency_seconds=overrides.get("detection_latency_seconds", 5.0),
        scheduled_hint_delay_minutes=overrides.get(
            "scheduled_hint_delay_minutes", None
        ),
        split_reason=overrides.get("split_reason", None),
        error_code=overrides.get("error_code", None),
        error_message=overrides.get("error_message", None),
        created_at=overrides.get("created_at", now),
        updated_at=overrides.get("updated_at", now),
    )
    repo.save(session)
    return session.id


# ── Tests ────────────────────────────────────────────────────────────────


class TestStopRecordingHandler:
    """StopRecordingHandler edge cases and delegation."""

    def test_stops_active_session(
        self,
        handler: StopRecordingHandler,
        session_repo: RecordingSessionRepository,
        target_repo: StreamTargetRepository,
        recording_service: MagicMock,
    ) -> None:
        """Active session \u2192 delegates to RecordingService.stop_recording."""
        session_id = _insert_session(
            session_repo,
            target_repo,
            id="active-1",
            status=RecordingStatus.RECORDING,
        )

        handler.handle(StopRecordingCommand(recording_id=session_id))

        recording_service.stop_recording.assert_called_once_with(session_id)

    def test_already_completed_is_idempotent(
        self,
        handler: StopRecordingHandler,
        session_repo: RecordingSessionRepository,
        target_repo: StreamTargetRepository,
        recording_service: MagicMock,
    ) -> None:
        """COMPLETED session \u2192 no delegation to RecordingService."""
        session_id = _insert_session(
            session_repo,
            target_repo,
            id="completed-1",
            status=RecordingStatus.COMPLETED,
        )

        handler.handle(StopRecordingCommand(recording_id=session_id))

        recording_service.stop_recording.assert_not_called()

    def test_already_failed_is_idempotent(
        self,
        handler: StopRecordingHandler,
        session_repo: RecordingSessionRepository,
        target_repo: StreamTargetRepository,
        recording_service: MagicMock,
    ) -> None:
        """FAILED session \u2192 no delegation to RecordingService."""
        session_id = _insert_session(
            session_repo,
            target_repo,
            id="failed-1",
            status=RecordingStatus.FAILED,
        )

        handler.handle(StopRecordingCommand(recording_id=session_id))

        recording_service.stop_recording.assert_not_called()

    def test_already_aborted_is_idempotent(
        self,
        handler: StopRecordingHandler,
        session_repo: RecordingSessionRepository,
        target_repo: StreamTargetRepository,
        recording_service: MagicMock,
    ) -> None:
        """ABORTED session \u2192 no delegation to RecordingService."""
        session_id = _insert_session(
            session_repo,
            target_repo,
            id="aborted-1",
            status=RecordingStatus.ABORTED,
        )

        handler.handle(StopRecordingCommand(recording_id=session_id))

        recording_service.stop_recording.assert_not_called()

    def test_already_split_is_idempotent(
        self,
        handler: StopRecordingHandler,
        session_repo: RecordingSessionRepository,
        target_repo: StreamTargetRepository,
        recording_service: MagicMock,
    ) -> None:
        """SPLIT session \u2192 no delegation to RecordingService."""
        session_id = _insert_session(
            session_repo,
            target_repo,
            id="split-1",
            status=RecordingStatus.SPLIT,
        )

        handler.handle(StopRecordingCommand(recording_id=session_id))

        recording_service.stop_recording.assert_not_called()

    def test_nonexistent_session_raises_value_error(
        self,
        handler: StopRecordingHandler,
        recording_service: MagicMock,
    ) -> None:
        """Nonexistent recording_id → ValueError."""
        with pytest.raises(ValueError, match="not found"):
            handler.handle(StopRecordingCommand(recording_id="does-not-exist"))

        recording_service.stop_recording.assert_not_called()
