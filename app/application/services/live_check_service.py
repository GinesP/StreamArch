"""LiveCheckService — bridges resolver chain with the resolve result store.

Performs a live check for a stream target by running it through the
resolver chain, then returns the result.

Snapshots are now managed in-memory by the :class:`MonitoringCycle`.
The resolve result is stored in the :class:`LiveCheckResultStore` and
consumed on the next monitoring cycle.
"""

from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.infrastructure.resolvers.resolver_chain import ResolverChain
from app.infrastructure.resolvers.result import ResolveResult


class LiveCheckService:
    """Performs a live check for a stream target and returns the result.

    Parameters
    ----------
    resolver_chain:
        Chain of resolvers tried in priority order.
    stream_target_repo:
        Repository for ``StreamTarget`` entities.
    """

    def __init__(
        self,
        resolver_chain: ResolverChain,
        stream_target_repo: StreamTargetRepository,
    ) -> None:
        self._resolver_chain = resolver_chain
        self._target_repo = stream_target_repo

    def check_stream(self, stream_id: str) -> ResolveResult:
        """Run a live check for *stream_id* and return the resolution result.

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

        return self._resolver_chain.resolve(target.source_url)
