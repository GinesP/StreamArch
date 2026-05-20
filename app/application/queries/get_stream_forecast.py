"""Get the interpreted forecast for a single stream target."""


class GetStreamForecastQuery:
    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


class GetStreamForecastHandler:
    def handle(self, query: GetStreamForecastQuery) -> dict:
        raise NotImplementedError
