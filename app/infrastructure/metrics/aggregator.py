"""MetricsAggregator — collects and persists compact time-bucketed metrics.

Avoids storing individual event noise; stores aggregated buckets instead.
"""


class MetricsAggregator:
    def record_dispatch(self, band: str, wait_seconds: float) -> None:
        raise NotImplementedError

    def record_detection(self, latency_seconds: float) -> None:
        raise NotImplementedError

    def flush_bucket(self) -> None:
        raise NotImplementedError
