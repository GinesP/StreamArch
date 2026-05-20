"""Disable monitoring for a stream target.

When monitoring is disabled:
    - The stream target's ``enabled`` flag is set to ``False``.
    - The monitoring snapshot is reset to ``IDLE`` and its ``queue_band``
      is cleared so the scheduler will skip this target.
    - No live check or recording will be initiated.
"""

from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import utc_now
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
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
    """Handles :class:`DisableMonitoringCommand` — disables and resets."""

    def __init__(
        self,
        stream_target_repo: StreamTargetRepository,
        monitoring_snapshot_repo: MonitoringSnapshotRepository,
    ) -> None:
        self._target_repo = stream_target_repo
        self._snapshot_repo = monitoring_snapshot_repo

    def handle(self, cmd: DisableMonitoringCommand) -> None:
        """Disable monitoring for *stream_id*.

        Raises ``ValueError`` if the stream target does not exist.
        Idempotent — no-op if already disabled.

        Target and snapshot updates are independent — the repository
        ``save()`` method now uses UPSERT semantics, so saving the
        target no longer triggers a cascade-delete on the snapshot.
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

        # ── Reset snapshot ─────────────────────────────────────────
        snapshot = self._snapshot_repo.get(cmd.stream_id)
        if snapshot is not None:
            snap_kwargs = {
                f.name: getattr(snapshot, f.name)
                for f in snapshot.__dataclass_fields__.values()
            }
            snap_kwargs["state"] = MonitoringState.IDLE
            snap_kwargs["queue_band"] = None
            snap_kwargs["updated_at"] = now
            self._snapshot_repo.save(snapshot.__class__(**snap_kwargs))
