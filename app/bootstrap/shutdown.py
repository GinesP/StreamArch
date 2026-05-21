"""Graceful shutdown sequence for the core application.

Closes DB, stops workers, persists state, and shuts down cleanly.
"""

from .container import Container


def shutdown_application(container: Container, reason: str = "shutdown") -> None:
    """Coordinate graceful shutdown of all subsystems.

    Args:
        container: The wired application container.
        reason: Short label for the shutdown cause (e.g. ``"shutdown"``,
                ``"sigint"``, ``"error"``).
    """
    container.logger.info("Shutting down StreamArch core (reason: %s)…", reason)

    # ── Stop the monitoring cycle ────────────────────────────────────
    if container.monitoring_cycle is not None:
        container.monitoring_cycle.stop()
        container.logger.info("Monitoring cycle stopped")

    # ── Stop the REST API server ────────────────────────────────────
    if container.api_server is not None:
        container.api_server.shutdown()
        container.logger.info("REST API server stopped")

    # No shared database connection to close — repositories use
    # connection-per-operation and manage their own lifecycle.
    container.logger.info("Shutdown complete")
