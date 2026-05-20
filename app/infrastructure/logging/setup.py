"""Logging configuration for technical and audit trails."""

import logging


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Set up root logger with console (and optional file) handler."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
