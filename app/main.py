"""StreamArch core — entry point.

Starts the core application: loads config, wires dependencies,
boots background workers, and starts the API server.

Usage:
    python -m app.main [--config path/to/config.yaml]
"""


def main() -> None:
    """Application entry point stub."""
    # TODO: parse CLI args
    # TODO: create container via bootstrap.startup.create_container()
    # TODO: start application via bootstrap.startup.start_application()
    # TODO: register signal handlers for graceful shutdown
    pass


if __name__ == "__main__":
    main()
