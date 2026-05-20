"""List recording sessions with optional filters."""


class ListRecordingsQuery:
    def __init__(self, stream_id: str | None = None) -> None:
        self.stream_id = stream_id


class ListRecordingsHandler:
    def handle(self, query: ListRecordingsQuery) -> list[dict]:
        raise NotImplementedError
