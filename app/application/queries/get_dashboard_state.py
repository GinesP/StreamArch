"""Get the global dashboard snapshot — system health, queues, streams.

Aggregates all stream targets with their monitoring snapshots and
returns summary counts so the UI can render a dashboard without
multiple round-trips.

Snapshots are read from the :class:`MonitoringCycle`'s in-memory store
instead of a database repository.
"""

from app.application.dto.streams import DashboardStateDTO, StreamOverviewDTO
from app.domain.monitoring.states import MonitoringState


class GetDashboardStateQuery:
    """Marker query — no parameters for now."""


def _classify(state: MonitoringState | None) -> str:
    """Return a category label for dashboard counts."""
    if state is None:
        return "idle"
    if state == MonitoringState.RECORDING:
        return "live"
    if state == MonitoringState.ERROR:
        return "error"
    return "idle"


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


class GetDashboardStateHandler:
    """Handles :class:`GetDashboardStateQuery` — returns aggregate state.

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

    def handle(self, query: GetDashboardStateQuery) -> DashboardStateDTO:
        targets = self._target_repo.list_all()
        snapshots = {
            s.stream_target_id: s
            for s in self._monitoring_cycle.get_all_snapshots()
        }

        live_count = 0
        error_count = 0
        idle_count = 0
        overviews: list[StreamOverviewDTO] = []

        for target in targets:
            snapshot = snapshots.get(target.id)
            state = snapshot.state if snapshot else None
            category = _classify(state)

            if category == "live":
                live_count += 1
            elif category == "error":
                error_count += 1
            else:
                idle_count += 1

            overviews.append(_build_overview(target, snapshot))

        return DashboardStateDTO(
            streams=overviews,
            total_count=len(targets),
            live_count=live_count,
            error_count=error_count,
            idle_count=idle_count,
        )
