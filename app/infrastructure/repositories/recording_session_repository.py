"""Repository for RecordingSession persistence."""

from app.domain.recording.session import RecordingSession


class RecordingSessionRepository:
    def save(self, session: RecordingSession) -> None:
        raise NotImplementedError

    def get(self, session_id: str) -> RecordingSession | None:
        raise NotImplementedError

    def list_by_target(self, stream_target_id: str) -> list[RecordingSession]:
        raise NotImplementedError

    def list_active(self) -> list[RecordingSession]:
        raise NotImplementedError
