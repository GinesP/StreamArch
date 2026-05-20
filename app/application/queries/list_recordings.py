"""List recording sessions with optional stream-target filter.

Returns a list of :class:`RecordingSessionDTO` objects — one per session —
ready for API or WebSocket presentation.
"""

from app.application.dto.recordings import RecordingSessionDTO
from app.domain.recording.session import RecordingSession
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)


class ListRecordingsQuery:
    """Query with an optional *stream_id* filter.

    When *stream_id* is ``None`` the handler returns all sessions; when set
    it returns only sessions belonging to that stream target.
    """

    def __init__(self, stream_id: str | None = None) -> None:
        self.stream_id = stream_id


def _build_dto(session: RecordingSession) -> RecordingSessionDTO:
    """Map a domain :class:`RecordingSession` to a serializable DTO."""
    return RecordingSessionDTO(
        id=session.id,
        stream_target_id=session.stream_target_id,
        started_at=session.started_at.isoformat(),
        ended_at=session.ended_at.isoformat() if session.ended_at else None,
        status=session.status.value,
        source_platform=session.source_platform.value,
        stream_title=session.stream_title,
        duration_seconds=session.duration_seconds,
        detected_by_queue=session.detected_by_queue.value
        if session.detected_by_queue
        else None,
        error_code=session.error_code,
        error_message=session.error_message,
        split_reason=session.split_reason,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


class ListRecordingsHandler:
    """Handles :class:`ListRecordingsQuery` — returns recording sessions."""

    def __init__(
        self,
        recording_session_repo: RecordingSessionRepository,
    ) -> None:
        self._repo = recording_session_repo

    def handle(self, query: ListRecordingsQuery) -> list[RecordingSessionDTO]:
        if query.stream_id is not None:
            sessions = self._repo.list_by_target(query.stream_id)
        else:
            sessions = self._repo.list_all()

        return [_build_dto(s) for s in sessions]
