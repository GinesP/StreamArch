"""Update an existing stream target's configuration."""


class UpdateStreamCommand:
    def __init__(self, stream_id: str, **fields) -> None:
        self.stream_id = stream_id
        self.fields = fields


class UpdateStreamHandler:
    def handle(self, cmd: UpdateStreamCommand) -> None:
        raise NotImplementedError
