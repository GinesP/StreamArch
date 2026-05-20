"""Repository for MetricsBucket persistence."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MetricsBucket:
    id: str
    bucket_start: datetime
    bucket_size_seconds: int
    queue_band: str
    total_dispatches: int
    total_live_detections: int
    avg_dispatch_wait_seconds: float | None
    p95_dispatch_wait_seconds: float | None
    avg_detection_latency_seconds: float | None
    sample_size: int
    created_at: datetime


class MetricsBucketRepository:
    def save(self, bucket: MetricsBucket) -> None:
        raise NotImplementedError

    def query_range(self, start: datetime, end: datetime) -> list[MetricsBucket]:
        raise NotImplementedError
