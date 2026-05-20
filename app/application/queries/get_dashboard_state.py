"""Get the global dashboard snapshot — system health, queues, streams."""


class GetDashboardStateQuery:
    pass


class GetDashboardStateHandler:
    def handle(self, query: GetDashboardStateQuery) -> dict:
        raise NotImplementedError
