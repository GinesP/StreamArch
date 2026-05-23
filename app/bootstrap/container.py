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
    recording_session_repo: object = None
    recording_artifact_repo: object = None
    metrics_bucket_repo: object = None

    # ── Services ──────────────────────────────────────────────────
    prediction_service: object = None
    recording_service: object = None
    health_service: object = None
    cookie_service: object = None
    live_check_service: object = None
    live_check_result_store: object = None

    # ── Infrastructure ────────────────────────────────────────────
    config: object = None
    logger: object = None
    file_manager: object = None
    ffmpeg_runner: object = None
    resolver_chain: object = None
    platform_semaphores: object = None
    queue_planner: object = None
    worker_pool: object = None
    event_bus: object = None

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
    disable_monitoring_handler: object = None
    enable_monitoring_handler: object = None
    mark_favorite_handler: object = None
    unmark_favorite_handler: object = None
    force_check_handler: object = None
    list_streams_handler: object = None
    get_dashboard_state_handler: object = None
    list_recordings_handler: object = None
    stop_recording_handler: object = None
