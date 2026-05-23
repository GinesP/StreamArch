"""Enable monitoring for a stream target.

When monitoring is enabled:
    - The stream target's ``enabled`` flag is set to ``True``.
    - The monitoring cycle is told to check the target immediately,
      so the stream does not wait for its old timer to expire.
"""

from app.application.orchestrators.monitoring_cycle import MonitoringCycle
from app.domain.shared.types import utc_now
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


# ── Command ────────────────────────────────────────────────────────────


class EnableMonitoringCommand:
    """Request: enable monitoring for a stream target."""

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


# ── Handler ────────────────────────────────────────────────────────────


class EnableMonitoringHandler:
    """Handles :class:`EnableMonitoringCommand` — enables monitoring."""

    def __init__(
        self,
        stream_target_repo: StreamTargetRepository,
        monitoring_cycle: MonitoringCycle,
    ) -> None:
        self._target_repo = stream_target_repo
        self._cycle = monitoring_cycle

    def handle(self, cmd: EnableMonitoringCommand) -> None:
        """Enable monitoring for *stream_id*.

        Raises ``ValueError`` if the stream target does not exist.
        Idempotent — no-op if already enabled.
        """
        target = self._target_repo.get(cmd.stream_id)
        if target is None:
            raise ValueError(f"Stream target {cmd.stream_id!r} not found")

        # Idempotent — already enabled.
        if target.enabled:
            return

        now = utc_now()

        kwargs = {
            f.name: getattr(target, f.name)
            for f in target.__dataclass_fields__.values()
        }
        kwargs["enabled"] = True
        kwargs["updated_at"] = now
        self._target_repo.save(target.__class__(**kwargs))

        # Force an immediate check so the stream doesn't wait for its
        # old timer (which may be minutes/hours in the future).
        self._cycle.force_next_check(cmd.stream_id)
