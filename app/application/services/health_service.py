"""HealthService — system health checks and diagnostics."""


class HealthService:
    def is_healthy(self) -> bool:
        raise NotImplementedError

    def get_health_report(self) -> dict:
        raise NotImplementedError
