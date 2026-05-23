"""Disable monitoring for a stream target.

When monitoring is disabled:
    - The stream target's ``enabled`` flag is set to ``False``.
    - No live check or recording will be initiated.
    - The in-memory snapshot is updated to IDLE by the next monitoring
      cycle if the target is re-enabled.
"""

from app.domain.shared.types import utc_now
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


# ── Command ────────────────────────────────────────────────────────────


class DisableMonitoringCommand:
    """Request: disable monitoring for a stream target."""

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


# ── Handler ────────────────────────────────────────────────────────────


class DisableMonitoringHandler:
    """Handles :class:`DisableMonitoringCommand` — disables monitoring."""

    def __init__(
        self,
        stream_target_repo: StreamTargetRepository,
    ) -> None:
        self._target_repo = stream_target_repo

    def handle(self, cmd: DisableMonitoringCommand) -> None:
        """Disable monitoring for *stream_id*.

        Raises ``ValueError`` if the stream target does not exist.
        Idempotent — no-op if already disabled.
        """
        target = self._target_repo.get(cmd.stream_id)
        if target is None:
            raise ValueError(f"Stream target {cmd.stream_id!r} not found")

        # Idempotent — already disabled.
        if not target.enabled:
            return

        now = utc_now()

        # ── Update target ──────────────────────────────────────────
        kwargs = {
            f.name: getattr(target, f.name)
            for f in target.__dataclass_fields__.values()
        }
        kwargs["enabled"] = False
        kwargs["updated_at"] = now
        self._target_repo.save(target.__class__(**kwargs))
