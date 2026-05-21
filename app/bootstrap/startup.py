"""Application startup sequence.

Loads config, configures logging, applies schema migrations, wires the
dependency container with live repository instances, and finally
instantiates the application-layer handlers.

Repositories use a connection-per-operation pattern — no shared
long-lived database connection is held in the container.
"""
import threading
from pathlib import Path

from app.application.orchestrators.monitoring_cycle import MonitoringCycle
from app.application.services.cookie_service import CookieService
from app.application.services.live_check_service import LiveCheckService
from app.application.commands.add_stream import AddStreamHandler
from app.application.commands.disable_monitoring import DisableMonitoringHandler
from app.application.commands.enable_monitoring import EnableMonitoringHandler
from app.application.commands.force_check import ForceCheckHandler
from app.application.commands.mark_favorite import MarkFavoriteHandler
from app.application.commands.unmark_favorite import UnmarkFavoriteHandler
from app.application.commands.update_stream import UpdateStreamHandler
from app.application.queries.list_recordings import ListRecordingsHandler
from app.application.queries.list_streams import ListStreamsHandler
from app.application.queries.get_dashboard_state import GetDashboardStateHandler
from app.infrastructure.config.loader import AppConfig, load_config
from app.infrastructure.cookies.cookie_storage import CookieStore
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.logging.setup import setup_logging
from app.domain.prediction.engine import PredictionEngine
from app.infrastructure.resolvers.resolver_chain import ResolverChain
from app.infrastructure.resolvers.streamget_resolver import StreamGetResolver
from app.infrastructure.resolvers.streamlink_resolver import StreamlinkResolver
from app.infrastructure.resolvers.ytdlp_resolver import YtDlpResolver
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.infrastructure.scheduler.platform_semaphores import PlatformSemaphores
from app.infrastructure.scheduler.queue_planner import QueuePlanner
from app.infrastructure.scheduler.worker_pool import WorkerPool
from app.interfaces.api.routes import build_router
from app.interfaces.api.server import create_server
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

    # Run migrations with a temporary connection (closed after use).
    conn = get_connection(db_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()

    # ── Repositories (connection-per-operation) ───────────────────
    container.stream_target_repo = StreamTargetRepository(str(db_path))
    container.monitoring_snapshot_repo = MonitoringSnapshotRepository(str(db_path))
    container.recording_session_repo = RecordingSessionRepository(str(db_path))

    # ── Cookie service ───────────────────────────────────────────
    container.cookie_service = CookieService(
        store=CookieStore(base_dir=container.config.cookies_dir),
    )

    # ── Resolvers & live-check service ───────────────────────────
    streamget_resolver = StreamGetResolver(
        cookie_service=container.cookie_service,
    )
    streamlink_resolver = StreamlinkResolver(
        cookie_service=container.cookie_service,
    )
    ytdlp_resolver = YtDlpResolver(
        cookie_service=container.cookie_service,
    )

    container.resolver_chain = ResolverChain(
        [streamget_resolver, streamlink_resolver, ytdlp_resolver],
    )

    container.live_check_service = LiveCheckService(
        resolver_chain=container.resolver_chain,
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
    )

    # ── Prediction engine & priority queue system ─────────────────
    container.prediction_engine = PredictionEngine()

    container.platform_semaphores = PlatformSemaphores(default_limit=3)
    container.queue_planner = QueuePlanner()
    container.worker_pool = WorkerPool(
        queue_planner=container.queue_planner,
        live_check_service=container.live_check_service,
        platform_semaphores=container.platform_semaphores,
        logger=container.logger,
    )
    container.worker_pool.start()

    container.monitoring_cycle = MonitoringCycle(
        prediction_engine=container.prediction_engine,
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
        recording_session_repo=container.recording_session_repo,
        queue_planner=container.queue_planner,
        logger=container.logger,
    )
    container.monitoring_cycle.start()

    # ── Application handlers ──────────────────────────────────────
    container.add_stream_handler = AddStreamHandler(
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
    )
    container.update_stream_handler = UpdateStreamHandler(
        stream_target_repo=container.stream_target_repo,
    )
    container.disable_monitoring_handler = DisableMonitoringHandler(
        stream_target_repo=container.stream_target_repo,
        monitoring_snapshot_repo=container.monitoring_snapshot_repo,
    )
    container.enable_monitoring_handler = EnableMonitoringHandler(
        stream_target_repo=container.stream_target_repo,
    )
    container.mark_favorite_handler = MarkFavoriteHandler(
        stream_target_repo=container.stream_target_repo,
    )
    container.unmark_favorite_handler = UnmarkFavoriteHandler(
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
    container.list_recordings_handler = ListRecordingsHandler(
        recording_session_repo=container.recording_session_repo,
    )
    container.force_check_handler = ForceCheckHandler(
        live_check_service=container.live_check_service,
    )

    # ── REST API server ──────────────────────────────────────────
    router = build_router()
    server = create_server(
        host=container.config.api_host,
        port=container.config.api_port,
        container=container,
        router=router,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    container.api_server = server

    container.logger.info("Database ready at %s", db_path)
    container.logger.info(
        "REST API listening on %s:%s",
        container.config.api_host,
        container.config.api_port,
    )
    container.logger.info("StreamArch core started successfully")
