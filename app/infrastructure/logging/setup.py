"""Console logging setup for the StreamArch core.

Single responsible: configure and return the ``streamarch`` logger
with a console handler.  No file handlers, no third-party libs.

All log timestamps are in UTC with an explicit ``Z`` suffix so there
is no ambiguity between local time (``%(asctime)s`` default) and the
UTC timestamps used throughout the domain.
"""

import logging
import sys
import time


def setup_logging(level: str = "INFO", fmt: str = "detailed") -> logging.Logger:
    """Configure the ``streamarch`` logger for console output.

    Parameters
    ----------
    level:
        One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``.
    fmt:
        ``"detailed"`` → UTC timestamp, level, name, message.
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
                "%(asctime)sZ [%(levelname)-7s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            formatter.converter = time.gmtime  # UTC instead of local time

        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
