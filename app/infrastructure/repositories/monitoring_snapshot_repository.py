"""Repository for MonitoringSnapshot persistence."""

from app.domain.monitoring.snapshot import MonitoringSnapshot


class MonitoringSnapshotRepository:
    def save(self, snapshot: MonitoringSnapshot) -> None:
        raise NotImplementedError

    def get(self, stream_target_id: str) -> MonitoringSnapshot | None:
        raise NotImplementedError

    def list_all(self) -> list[MonitoringSnapshot]:
        raise NotImplementedError
