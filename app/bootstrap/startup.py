"""Application startup sequence.

Loads config, configures logging, wires the dependency container.
"""

from app.infrastructure.config.loader import AppConfig, load_config
from app.infrastructure.logging.setup import setup_logging
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
    """Signal that the core is ready to operate.

    Future: this will start the scheduler, workers, API server, etc.
    """
    container.logger.info("StreamArch core started successfully")
