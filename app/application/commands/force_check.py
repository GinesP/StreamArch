"""Force an immediate live check for a stream target.

Triggers the resolver chain for the given stream and updates the
monitoring runtime state with the result.
"""

from app.application.orchestrators.monitoring_cycle import MonitoringCycle
from app.application.services.live_check_service import LiveCheckService
from app.application.services.live_check_result_store import LiveCheckResultStore
from app.infrastructure.resolvers.result import ResolveResult


class ForceCheckCommand:
    """Request: force a live check for a stream target."""

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


class ForceCheckHandler:
    """Handles :class:`ForceCheckCommand` — resolves and persists."""

    def __init__(
        self,
        live_check_service: LiveCheckService,
        result_store: LiveCheckResultStore,
        monitoring_cycle: MonitoringCycle,
    ) -> None:
        self._service = live_check_service
        self._result_store = result_store
        self._cycle = monitoring_cycle

    def handle(self, cmd: ForceCheckCommand) -> ResolveResult:
        """Run a live check, store the result for the next cycle, and
        force the runtime state to pick it up.

        Raises ``ValueError`` if the stream target does not exist.
        """
        result = self._service.check_stream(cmd.stream_id)
        self._result_store.store(cmd.stream_id, result)
        self._cycle.force_next_check(cmd.stream_id)
        return result
