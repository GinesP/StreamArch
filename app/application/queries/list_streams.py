"""List all registered stream targets with current state."""


class ListStreamsQuery:
    pass


class ListStreamsHandler:
    def handle(self, query: ListStreamsQuery) -> list[dict]:
        raise NotImplementedError
