"""RecordingService — coordinates RecordingEngine with session lifecycle."""


class RecordingService:
    def start_recording(self, stream_target_id: str, stream_url: str) -> str:
        """Start recording and return recording session id."""
        raise NotImplementedError

    def stop_recording(self, recording_session_id: str) -> None:
        raise NotImplementedError
