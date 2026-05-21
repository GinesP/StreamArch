"""Force an immediate live check for a stream target.

Triggers the resolver chain for the given stream and updates the
monitoring snapshot with the result.
"""

from app.application.services.live_check_service import LiveCheckService
from app.infrastructure.resolvers.result import ResolveResult


class ForceCheckCommand:
    """Request: force a live check for a stream target."""

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


class ForceCheckHandler:
    """Handles :class:`ForceCheckCommand` — resolves and persists."""

    def __init__(self, live_check_service: LiveCheckService) -> None:
        self._service = live_check_service

    def handle(self, cmd: ForceCheckCommand) -> ResolveResult:
        """Run a live check and return the resolution result.

        Raises ``ValueError`` if the stream target does not exist.
        """
        return self._service.check_stream(cmd.stream_id)
