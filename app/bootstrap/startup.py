"""Application startup sequence.

Loads config, opens DB, applies migrations, wires dependencies,
and starts background workers.
"""

from .container import Container


def create_container(config_path: str | None = None) -> Container:
    """Build and return the fully wired dependency container.

    This is a stub — actual wiring happens as components are implemented.
    """
    container = Container()
    # TODO: wire actual dependencies here
    return container


def start_application(container: Container) -> None:
    """Boot the core — start scheduler, workers, and API server.

    Stub — actual startup sequence TBD.
    """
    pass
