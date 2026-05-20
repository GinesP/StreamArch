"""Application startup sequence.

Loads config, configures logging, opens the database, applies schema
migrations, wires the dependency container with live repository
instances, and finally instantiates the application-layer handlers.
"""

from pathlib import Path

from app.application.commands.add_stream import AddStreamHandler
from app.application.commands.update_stream import UpdateStreamHandler
from app.application.queries.list_streams import ListStreamsHandler
from app.application.queries.get_dashboard_state import GetDashboardStateHandler
from app.infrastructure.config.loader import AppConfig, load_config
from app.infrastructure.db.connection import create_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.logging.setup import setup_logging
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from .container import Container


def create_container(config_path: str | None = None) -> Container:
    """Build and return the wired dependency container.

    1. Load configuration (from file or defaults).
    2. Configure the ``streamarch`` logger.
    3. Return a ``Container`` carrying both.
    """
    config: AppConfig = load_config(config_path)
    logger = setup_logging(config.log_level, config.log_format)

    source = f"file: {config_path}" if config_path else "defaults"
    logger.info("Starting StreamArch core\u2026")
    logger.info("Config loaded from %s", source)

    return Container(config=config, logger=logger)


def start_application(container: Container) -> None:
    """Open the database, apply migrations, wire repositories and handlers.

    After this call the container carries live repository instances
    and application handlers ready for use.
    """
    db_path = Path(container.config.db_path)
    conn = create_connection(db_path)
    apply_migrations(conn)
    container.db_connection = conn

    # ── Repositories ──────────────────────────────────────────────
    container.stream_target_repo = StreamTargetRepository(conn)
    container.monitoring_snapshot_repo = MonitoringSnapshotRepository(conn)
    container.recording_session_repo = RecordingSessionRepository(conn)

    # ── Application handlers ──────────────────────────────────────
    container.add_stream_handler = AddStreamHandler(
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
    )
    container.update_stream_handler = UpdateStreamHandler(
        stream_target_repo=container.stream_target_repo,
    )
    container.list_streams_handler = ListStreamsHandler(
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
    )
    container.get_dashboard_state_handler = GetDashboardStateHandler(
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
    )

    container.logger.info("Database ready at %s", db_path)
    container.logger.info("StreamArch core started successfully")
