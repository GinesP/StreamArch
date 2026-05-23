"""Thread-safe store for live check results from worker threads.

Workers write :class:`ResolveResult` objects here after completing a live
check.  The :class:`MonitoringCycle` consumes them in its next cycle to
update in-memory snapshots.

Thread safety is provided by a :class:`threading.Lock`.
"""

import threading

from app.infrastructure.resolvers.result import ResolveResult


class LiveCheckResultStore:
    """Thread-safe mapping of stream_id → latest ResolveResult."""

    def __init__(self) -> None:
        self._results: dict[str, ResolveResult] = {}
        self._lock = threading.Lock()

    def store(self, stream_id: str, result: ResolveResult) -> None:
        """Store the latest resolve result for *stream_id*.

        Thread-safe — callable from worker threads.
        """
        with self._lock:
            self._results[stream_id] = result

    def consume(self, stream_id: str) -> ResolveResult | None:
        """Return and remove the stored result for *stream_id* (or ``None``)."""
        with self._lock:
            return self._results.pop(stream_id, None)
