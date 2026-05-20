"""Maps between domain StreamTarget and API request/response payloads."""

from app.domain.stream_target.entities import StreamTarget


class StreamMapper:
    @staticmethod
    def from_request(data: dict) -> StreamTarget:
        """Map an API creation request to a StreamTarget entity."""
        raise NotImplementedError

    @staticmethod
    def to_response(target: StreamTarget) -> dict:
        """Map a StreamTarget entity to an API response."""
        raise NotImplementedError
