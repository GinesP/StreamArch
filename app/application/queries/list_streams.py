"""List all registered stream targets with their current monitoring state.

Returns a list of :class:`StreamOverviewDTO` objects — one per target,
merged with the latest snapshot data so callers (API, WebSocket, CLI)
have everything in one pass.
"""

from app.application.dto.streams import StreamOverviewDTO
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


class ListStreamsQuery:
    """Marker query — no parameters needed at this stage."""


def _build_overview(target, snapshot) -> StreamOverviewDTO:
    """Merge a stream target and its optional snapshot into an overview."""
    return StreamOverviewDTO(
        id=target.id,
        platform=target.platform.value,
        handle=target.handle,
        display_name=target.display_name,
        enabled=target.enabled,
        favorite=target.favorite,
        state=snapshot.state.value if snapshot else "unknown",
        queue_band=snapshot.queue_band.value if snapshot and snapshot.queue_band else None,
        current_likelihood=snapshot.current_likelihood if snapshot else 0.0,
        current_confidence=snapshot.current_confidence.value if snapshot else "low",
        next_check_at=snapshot.next_check_at.isoformat()
        if snapshot and snapshot.next_check_at
        else None,
        last_live_at=snapshot.last_live_at.isoformat()
        if snapshot and snapshot.last_live_at
        else None,
    )


class ListStreamsHandler:
    """Handles :class:`ListStreamsQuery` — returns all streams with state."""

    def __init__(
        self,
        stream_target_repo: StreamTargetRepository,
        monitoring_snapshot_repo: MonitoringSnapshotRepository,
    ) -> None:
        self._target_repo = stream_target_repo
        self._snapshot_repo = monitoring_snapshot_repo

    def handle(self, query: ListStreamsQuery) -> list[StreamOverviewDTO]:
        targets = self._target_repo.list_all()
        snapshots = {s.stream_target_id: s for s in self._snapshot_repo.list_all()}

        return [_build_overview(t, snapshots.get(t.id)) for t in targets]
