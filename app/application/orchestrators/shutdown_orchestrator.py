"""ShutdownOrchestrator — coordinates a graceful system shutdown.

Ensures in-flight recordings are safely closed and state is persisted.
"""


class ShutdownOrchestrator:
    def shutdown(self, reason: str) -> None:
        raise NotImplementedError
