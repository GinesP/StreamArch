"""Add a new stream target to monitoring."""


class AddStreamCommand:
    """Request: register a new stream target."""

    def __init__(self, platform: str, handle: str, source_url: str, display_name: str) -> None:
        self.platform = platform
        self.handle = handle
        self.source_url = source_url
        self.display_name = display_name


class AddStreamHandler:
    """Handles AddStreamCommand — validates and persists."""

    def handle(self, cmd: AddStreamCommand) -> str:
        """Execute and return the new stream target id."""
        raise NotImplementedError
