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

    # ── Stop all active recordings (finalises sessions in DB) ────────
    if container.recording_service is not None:
        container.recording_service.stop_all()
        container.logger.info("Recording service stopped (all sessions finalised)")
    elif container.ffmpeg_runner is not None:
        # Fallback: no recording service wired — just stop ffmpeg.
        container.ffmpeg_runner.stop_all()
        container.logger.info("FFmpeg runner stopped (fallback — sessions NOT finalised)")

    # ── Stop the worker pool (waits for in-flight checks) ─────────────
    if container.worker_pool is not None:
        container.worker_pool.stop()
        container.logger.info("Worker pool stopped")

    # ── Stop the WebSocket server ──────────────────────────────────
    if container.websocket_handler is not None:
        container.websocket_handler.stop()
        container.logger.info("WebSocket server stopped")

    # ── Stop the REST API server ────────────────────────────────────
    if container.api_server is not None:
        container.api_server.shutdown()
        container.logger.info("REST API server stopped")

    # No shared database connection to close — repositories use
    # connection-per-operation and manage their own lifecycle.
    container.logger.info("Shutdown complete")
