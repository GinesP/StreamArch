"""Disable monitoring for a stream target."""


class DisableMonitoringCommand:
    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


class DisableMonitoringHandler:
    def handle(self, cmd: DisableMonitoringCommand) -> None:
        raise NotImplementedError
