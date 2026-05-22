"""LiveCheckService — bridges resolver chain with persistence layer.

Performs a live check for a stream target by running it through the
resolver chain, then updates the monitoring snapshot based on what
the resolver reports.

This is the *manual* check path — the scheduler will call the same
service later for automated checks.
"""

from datetime import timedelta

from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence, utc_now
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.infrastructure.resolvers.resolver_chain import ResolverChain
from app.infrastructure.resolvers.result import ResolveResult

# ── Defaults ────────────────────────────────────────────────────────────

_DEFAULT_CHECK_INTERVAL_SECONDS: int = 300  # 5 minutes


class LiveCheckService:
    """Performs a live check for a stream target and updates its snapshot.

    Parameters
    ----------
    resolver_chain:
        Chain of resolvers tried in priority order.
    stream_target_repo:
        Repository for ``StreamTarget`` entities.
    monitoring_snapshot_repo:
        Repository for ``MonitoringSnapshot`` summaries.
    """

    def __init__(
        self,
        resolver_chain: ResolverChain,
        stream_target_repo: StreamTargetRepository,
        monitoring_snapshot_repo: MonitoringSnapshotRepository,
    ) -> None:
        self._resolver_chain = resolver_chain
        self._target_repo = stream_target_repo
        self._snapshot_repo = monitoring_snapshot_repo

    def check_stream(self, stream_id: str) -> ResolveResult:
        """Run a live check for *stream_id*, persist the outcome, and return the
        resolution result.

        Parameters
        ----------
        stream_id:
            The ``StreamTarget.id`` to check.

        Returns
        -------
        ResolveResult
            The outcome of the resolution (never ``None``).

        Raises
        ------
        ValueError
            When *stream_id* does not match any known stream target.
        """
        target = self._target_repo.get(stream_id)
        if target is None:
            raise ValueError(f"Stream target {stream_id!r} not found")

        result = self._resolver_chain.resolve(target.source_url)

        now = utc_now()
        snapshot = self._snapshot_repo.get(stream_id)

        if result.is_live:
            state = MonitoringState.RECORDING
            likelihood = 1.0
            last_live_at = now
            resolved_stream_url = result.stream_url
        else:
            state = MonitoringState.IDLE
            likelihood = 0.0
            # Preserve the last-known live timestamp when offline.
            last_live_at = snapshot.last_live_at if snapshot else None
            resolved_stream_url = None

        next_check_at = now + timedelta(seconds=_DEFAULT_CHECK_INTERVAL_SECONDS)

        if snapshot is not None:
            # ── Update existing snapshot in-place ────────────────
            snap_kwargs = {
                f.name: getattr(snapshot, f.name)
                for f in snapshot.__dataclass_fields__.values()
            }
            snap_kwargs["state"] = state
            snap_kwargs["current_likelihood"] = likelihood
            snap_kwargs["queue_band"] = None
            snap_kwargs["next_check_at"] = next_check_at
            snap_kwargs["last_checked_at"] = now
            snap_kwargs["last_live_at"] = last_live_at
            snap_kwargs["resolved_stream_url"] = resolved_stream_url
            snap_kwargs["updated_at"] = now
            self._snapshot_repo.save(snapshot.__class__(**snap_kwargs))
        else:
            # ── First check — create a brand-new snapshot ────────
            new_snapshot = MonitoringSnapshot(
                stream_target_id=stream_id,
                state=state,
                queue_band=None,
                current_likelihood=likelihood,
                current_confidence=Confidence.LOW,
                next_check_at=next_check_at,
                last_checked_at=now,
                last_live_at=last_live_at,
                current_recording_session_id=None,
                resolved_stream_url=resolved_stream_url,
                last_error_code=None,
                last_error_message=None,
                updated_at=now,
            )
            self._snapshot_repo.save(new_snapshot)

        return result
