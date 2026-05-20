"""Repository for StreamTarget persistence."""

from app.domain.stream_target.entities import StreamTarget


class StreamTargetRepository:
    def save(self, target: StreamTarget) -> None:
        raise NotImplementedError

    def get(self, target_id: str) -> StreamTarget | None:
        raise NotImplementedError

    def list_all(self) -> list[StreamTarget]:
        raise NotImplementedError

    def delete(self, target_id: str) -> None:
        raise NotImplementedError
