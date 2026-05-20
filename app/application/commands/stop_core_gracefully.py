"""Request a graceful shutdown of the core system."""


class StopCoreGracefullyCommand:
    def __init__(self, reason: str = "user_request") -> None:
        self.reason = reason


class StopCoreGracefullyHandler:
    def handle(self, cmd: StopCoreGracefullyCommand) -> None:
        raise NotImplementedError
