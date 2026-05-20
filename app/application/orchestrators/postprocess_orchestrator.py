"""PostprocessOrchestrator — manages remux/transmux after recording.

Chains ffmpeg re-muxing and artifact status updates.
"""


class PostprocessOrchestrator:
    def process_session(self, recording_session_id: str) -> None:
        raise NotImplementedError
