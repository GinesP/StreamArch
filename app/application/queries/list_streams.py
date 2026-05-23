"""List all registered stream targets with their current monitoring state.

Returns a list of :class:`StreamOverviewDTO` objects — one per target,
merged with the latest snapshot data so callers (API, WebSocket, CLI)
have everything in one pass.

Snapshots are read from the :class:`MonitoringCycle`'s in-memory store
instead of a database repository.
"""

from app.application.dto.streams import StreamOverviewDTO


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


class ListStreamsQuery:
    """Marker query — no parameters needed at this stage."""


class ListStreamsHandler:
    """Handles :class:`ListStreamsQuery` — returns all streams with state.

    Parameters
    ----------
    stream_target_repo:
        Repository for ``StreamTarget`` entities.
    monitoring_cycle:
        The ``MonitoringCycle`` that owns the in-memory snapshots.
    """

    def __init__(self, stream_target_repo, monitoring_cycle) -> None:
        self._target_repo = stream_target_repo
        self._monitoring_cycle = monitoring_cycle

    def handle(self, query: ListStreamsQuery) -> list[StreamOverviewDTO]:
        targets = self._target_repo.list_all()
        snapshots = {
            s.stream_target_id: s
            for s in self._monitoring_cycle.get_all_snapshots()
        }

        return [_build_overview(t, snapshots.get(t.id)) for t in targets]
