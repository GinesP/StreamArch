"""Simple dependency injection container.

Wires together domain, application, and infrastructure components.
Handlers are populated during startup after repositories are created.
"""

from dataclasses import dataclass, field


@dataclass
class Container:
    """Carries every wired dependency for the application.

    Attributes are ``None`` until ``start_application()`` populates them.
    """

    # ── Repositories ──────────────────────────────────────────────
    stream_target_repo: object = None
    monitoring_snapshot_repo: object = None
    recording_session_repo: object = None
    metrics_bucket_repo: object = None

    # ── Services ──────────────────────────────────────────────────
    prediction_service: object = None
    recording_service: object = None
    health_service: object = None

    # ── Infrastructure ────────────────────────────────────────────
    config: object = None
    logger: object = None
    file_manager: object = None

    # ── Domain ────────────────────────────────────────────────────
    prediction_engine: object = None

    # ── Interfaces ────────────────────────────────────────────────
    websocket_handler: object = None
    api_server: object = None

    # ── Orchestrators ─────────────────────────────────────────────
    monitoring_cycle: object = None
    shutdown_orchestrator: object = None
    postprocess_orchestrator: object = None

    # ── Application handlers ──────────────────────────────────────
    add_stream_handler: object = None
    update_stream_handler: object = None
    list_streams_handler: object = None
    get_dashboard_state_handler: object = None
