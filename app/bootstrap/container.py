"""Simple dependency injection container.

Wires together domain, application, and infrastructure components.
To be populated during bootstrap as dependencies are implemented.
"""

from dataclasses import dataclass, field


@dataclass
class Container:
    # Repositories
    stream_target_repo: object = None
    monitoring_snapshot_repo: object = None
    recording_session_repo: object = None
    metrics_bucket_repo: object = None

    # Services
    prediction_service: object = None
    recording_service: object = None
    health_service: object = None

    # Infrastructure
    config: object = None
    logger: object = None
    db_connection: object = None
    file_manager: object = None

    # Domain
    prediction_engine: object = None

    # Interfaces
    websocket_handler: object = None

    # Orchestrators
    monitoring_cycle: object = None
    shutdown_orchestrator: object = None
    postprocess_orchestrator: object = None
