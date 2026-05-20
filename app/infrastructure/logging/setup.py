"""Console logging setup for the StreamArch core.

Single responsible: configure and return the ``streamarch`` logger
with a console handler.  No file handlers, no third-party libs.
"""

import logging
import sys


def setup_logging(level: str = "INFO", fmt: str = "detailed") -> logging.Logger:
    """Configure the ``streamarch`` logger for console output.

    Parameters
    ----------
    level:
        One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``.
    fmt:
        ``"detailed"`` → timestamp, level, name, message.
        ``"simple"``   → level and message only.

    Returns
    -------
    The ``streamarch`` logger instance (callers should **not** create
    their own loggers — use ``logging.getLogger("streamarch")``).
    """
    logger = logging.getLogger("streamarch")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)

        if fmt == "simple":
            formatter = logging.Formatter("%(levelname)s: %(message)s")
        else:
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
