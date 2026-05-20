"""StreamArch core — entry point.

Parses CLI arguments, bootstraps the container, runs until a shutdown
signal is received, then exits cleanly.

Usage::

    python -m app.main
    python -m app.main --config config.example.json
"""

import argparse
import logging
import signal
import sys
import threading
import traceback

from app.bootstrap.container import Container
from app.bootstrap.startup import create_container, start_application
from app.bootstrap.shutdown import shutdown_application

# ── Shutdown coordination ────────────────────────────────────────────

_shutdown_event = threading.Event()


def _request_shutdown() -> None:
    """Set the shutdown event — called by signal handlers."""
    _shutdown_event.set()


def _register_signal_handlers() -> None:
    """Install handlers for SIGINT (Ctrl+C) and SIGTERM (when available)."""
    signal.signal(signal.SIGINT, lambda signum, frame: _request_shutdown())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda signum, frame: _request_shutdown())


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="StreamArch core engine")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON configuration file (optional — uses defaults)",
    )
    args = parser.parse_args()

    _register_signal_handlers()

    container: Container | None = None

    try:
        container = create_container(args.config)
        start_application(container)

        # Block until shutdown is requested (Ctrl+C, SIGTERM, …)
        _shutdown_event.wait()

    except KeyboardInterrupt:
        # Fallback: some platforms deliver KeyboardInterrupt instead
        # of going through our SIGINT handler.
        _request_shutdown()

    except Exception:
        logger = _try_get_logger(container)
        if logger:
            logger.exception("Unhandled exception — forcing shutdown")
        else:
            traceback.print_exc()
    finally:
        if container is not None:
            shutdown_application(container, reason="sigint")
        sys.exit(0)


def _try_get_logger(container: Container | None) -> logging.Logger | None:
    """Return the application logger if the container was bootstrapped."""
    if container is not None:
        return getattr(container, "logger", None)
    return None


if __name__ == "__main__":
    main()
