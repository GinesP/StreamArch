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

    if container.api_server is not None:
        container.api_server.shutdown()
        container.logger.info("REST API server stopped")

    if container.db_connection is not None:
        container.db_connection.close()
        container.logger.info("Database connection closed")

    container.logger.info("Shutdown complete")
