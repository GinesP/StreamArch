"""Graceful shutdown sequence for the core application.

Closes DB, stops ffmpeg processes, persists state, and shuts down workers.
"""

from .container import Container


def shutdown_application(container: Container, reason: str = "shutdown") -> None:
    """Coordinate graceful shutdown of all subsystems.

    Stub — actual shutdown logic TBD.
    """
    # 1. Stop scheduler / workers
    # 2. Close active recordings
    # 3. Run post-processing if needed
    # 4. Persist final state
    # 5. Close DB
    # 6. Stop event bus
    pass
