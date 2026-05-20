"""Application startup sequence.

Loads config, configures logging, opens the database, applies schema
migrations, and wires the dependency container with live repository
instances.
"""

from pathlib import Path

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
    logger.info("Starting StreamArch core…")
    logger.info("Config loaded from %s", source)

    return Container(config=config, logger=logger)


def start_application(container: Container) -> None:
    """Open the database, apply migrations, and wire repositories.

    After this call the container carries live repository instances
    ready for use by application services.
    """
    db_path = Path(container.config.db_path)
    conn = create_connection(db_path)
    apply_migrations(conn)
    container.db_connection = conn

    container.stream_target_repo = StreamTargetRepository(conn)
    container.monitoring_snapshot_repo = MonitoringSnapshotRepository(conn)
    container.recording_session_repo = RecordingSessionRepository(conn)

    container.logger.info("Database ready at %s", db_path)
    container.logger.info("StreamArch core started successfully")
