"""Graceful shutdown sequence for the core application.

Closes DB, stops workers, persists state, and shuts down cleanly.
Currently a placeholder — the shutdown contract is established here
and will be filled as subsystems are implemented.
"""

from .container import Container


def shutdown_application(container: Container, reason: str = "shutdown") -> None:
    """Coordinate graceful shutdown of all subsystems.

    Args:
        container: The wired application container.
        reason: Short label for the shutdown cause (e.g. "shutdown",
                "sigint", "error").
    """
    container.logger.info("Shutting down StreamArch core (reason: %s)…", reason)
    # Future: close DB, stop scheduler, terminate ffmpeg, persist state
    container.logger.info("Shutdown complete")
