"""Stop an active recording session.

This is the application-layer command that bridges the REST API with
:class:`RecordingService.stop_recording`.  It validates the session
exists and is active before delegating to the service, and raises
``ValueError`` (→ HTTP 400) when the session is not found.
"""

from app.application.services.recording_service import RecordingService
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)


# ── Command ────────────────────────────────────────────────────────────


class StopRecordingCommand:
    """Request: stop the recording identified by *recording_id*."""

    def __init__(self, recording_id: str) -> None:
        self.recording_id = recording_id


# ── Handler ────────────────────────────────────────────────────────────


class StopRecordingHandler:
    """Handles :class:`StopRecordingCommand`.

    Idempotent — stopping an already-finished session is a no-op.  A
    nonexistent session raises ``ValueError``.
    """

    def __init__(
        self,
        recording_session_repo: RecordingSessionRepository,
        recording_service: RecordingService,
    ) -> None:
        self._repo = recording_session_repo
        self._service = recording_service

    def handle(self, cmd: StopRecordingCommand) -> None:
        """Stop the recording session.

        Raises ``ValueError`` if the session does not exist.
        Idempotent for already-finished sessions.
        """
        session = self._repo.get(cmd.recording_id)
        if session is None:
            raise ValueError(
                f"Recording session {cmd.recording_id!r} not found"
            )

        # Idempotent — session is already finished.
        if not session.is_active:
            return

        self._service.stop_recording(cmd.recording_id)
