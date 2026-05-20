"""Force an immediate live check for a stream target."""


class ForceCheckCommand:
    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


class ForceCheckHandler:
    def handle(self, cmd: ForceCheckCommand) -> None:
        raise NotImplementedError
