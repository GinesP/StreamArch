"""Contract tests for the REST API.

Tests the HTTP surface directly — uses a temporary file-based SQLite
database and a real ``HTTPServer`` on a random local port.

The database is connection-per-operation (same as production), so each
request handler creates its own short-lived connections.
"""

import json
import socket
import threading
from http.client import HTTPConnection
from http.server import HTTPServer
from unittest.mock import MagicMock

import pytest

from app.application.commands.add_stream import AddStreamCommand, AddStreamHandler
from app.application.commands.disable_monitoring import (
    DisableMonitoringCommand,
    DisableMonitoringHandler,
)
from app.application.commands.enable_monitoring import (
    EnableMonitoringCommand,
    EnableMonitoringHandler,
)
from app.application.commands.force_check import ForceCheckCommand, ForceCheckHandler
from app.application.commands.mark_favorite import (
    MarkFavoriteCommand,
    MarkFavoriteHandler,
)
from app.application.commands.unmark_favorite import (
    UnmarkFavoriteCommand,
    UnmarkFavoriteHandler,
)
from app.application.commands.update_stream import UpdateStreamHandler
from app.application.queries.get_dashboard_state import (
    GetDashboardStateHandler,
    GetDashboardStateQuery,
)
from app.application.queries.list_recordings import (
    ListRecordingsHandler,
    ListRecordingsQuery,
)
from app.application.queries.list_streams import ListStreamsHandler, ListStreamsQuery
from app.application.services.cookie_service import CookieService
from app.application.services.live_check_service import LiveCheckService
from app.bootstrap.container import Container
from app.infrastructure.cookies.cookie_storage import CookieStore
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.resolvers.resolver_chain import ResolverChain
from app.infrastructure.resolvers.result import ResolveResult
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.interfaces.api.routes import build_router
from app.interfaces.api.server import APIHandler, create_server

# ── Sample data ─────────────────────────────────────────────────────────

SAMPLE_PUPPETEER_JSON = [
    {
        "name": "sessionid",
        "value": "abc123",
        "domain": ".twitch.tv",
        "path": "/",
        "httpOnly": True,
        "secure": True,
    },
    {
        "name": "persistent",
        "value": "xyz789",
        "domain": ".twitch.tv",
        "path": "/",
        "httpOnly": True,
        "secure": True,
    },
    {
        "name": "login_token",
        "value": "tok_42",
        "domain": "twitch.tv",
        "path": "/",
        "httpOnly": False,
        "secure": False,
    },
]


# ── Helpers ────────────────────────────────────────────────────────────


def _free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _json_request(
    conn: HTTPConnection,
    method: str,
    path: str,
    body: dict | None = None,
) -> tuple[int, dict]:
    """Send an HTTP request and return ``(status, parsed_body)``."""
    headers = {"Content-Type": "application/json"}
    raw = json.dumps(body).encode("utf-8") if body is not None else None
    conn.request(method, path, body=raw, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    return resp.status, data


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path) -> str:
    """Create a temp database with schema applied."""
    path = tmp_path / "test.db"
    conn = get_connection(path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return str(path)


@pytest.fixture
def container(db_path, tmp_path) -> Container:
    c = Container()
    c.stream_target_repo = StreamTargetRepository(db_path)
    c.monitoring_snapshot_repo = MonitoringSnapshotRepository(db_path)
    c.recording_session_repo = RecordingSessionRepository(db_path)

    c.cookie_service = CookieService(
        store=CookieStore(base_dir=str(tmp_path / "cookies")),
    )

    c.add_stream_handler = AddStreamHandler(
        stream_target_repo=c.stream_target_repo,
        monitoring_snapshot_repo=c.monitoring_snapshot_repo,
    )
    c.disable_monitoring_handler = DisableMonitoringHandler(
        stream_target_repo=c.stream_target_repo,
        monitoring_snapshot_repo=c.monitoring_snapshot_repo,
    )
    c.enable_monitoring_handler = EnableMonitoringHandler(
        stream_target_repo=c.stream_target_repo,
    )
    c.mark_favorite_handler = MarkFavoriteHandler(
        stream_target_repo=c.stream_target_repo,
    )
    c.unmark_favorite_handler = UnmarkFavoriteHandler(
        stream_target_repo=c.stream_target_repo,
    )
    c.update_stream_handler = UpdateStreamHandler(
        stream_target_repo=c.stream_target_repo,
    )
    c.list_streams_handler = ListStreamsHandler(
        stream_target_repo=c.stream_target_repo,
        monitoring_snapshot_repo=c.monitoring_snapshot_repo,
    )
    c.get_dashboard_state_handler = GetDashboardStateHandler(
        stream_target_repo=c.stream_target_repo,
        monitoring_snapshot_repo=c.monitoring_snapshot_repo,
    )
    c.list_recordings_handler = ListRecordingsHandler(
        recording_session_repo=c.recording_session_repo,
    )

    # ── Live-check (mocked chain, real repos) ─────────────────────
    c.resolver_chain = ResolverChain([
        MagicMock(resolve=MagicMock(return_value=ResolveResult(
            is_live=False,
        ))),
    ])
    c.live_check_service = LiveCheckService(
        resolver_chain=c.resolver_chain,
        stream_target_repo=c.stream_target_repo,
        monitoring_snapshot_repo=c.monitoring_snapshot_repo,
    )
    c.force_check_handler = ForceCheckHandler(
        live_check_service=c.live_check_service,
    )
    return c


@pytest.fixture
def server(container) -> HTTPServer:
    port = _free_port()
    router = build_router()
    srv = create_server("127.0.0.1", port, container, router, quiet=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()


@pytest.fixture
def conn(server) -> HTTPConnection:
    """Return an HTTP connection to the test server (close after use)."""
    c = HTTPConnection("127.0.0.1", server.server_port)
    try:
        yield c
    finally:
        c.close()


# ── Tests ──────────────────────────────────────────────────────────────


class TestApiContract:
    """End-to-end contract tests exercising the HTTP surface."""

    def test_get_streams_empty(self, conn: HTTPConnection) -> None:
        status, data = _json_request(conn, "GET", "/api/v1/streams")
        assert status == 200
        assert data == {"items": []}

    def test_create_and_list(self, conn: HTTPConnection) -> None:
        body = {
            "platform": "twitch",
            "handle": "teststreamer",
            "source_url": "https://twitch.tv/teststreamer",
            "display_name": "Test Streamer",
        }

        status, data = _json_request(conn, "POST", "/api/v1/streams", body)
        assert status == 201
        assert "id" in data
        stream_id = data["id"]

        status, data = _json_request(conn, "GET", "/api/v1/streams")
        assert status == 200
        assert len(data["items"]) == 1
        assert data["items"][0]["handle"] == "teststreamer"
        assert data["items"][0]["id"] == stream_id

    def test_update_stream(self, conn: HTTPConnection) -> None:
        # Arrange — create a stream
        _, create_data = _json_request(
            conn,
            "POST",
            "/api/v1/streams",
            {
                "platform": "youtube",
                "handle": "ytchannel",
                "source_url": "https://youtube.com/@ytchannel",
                "display_name": "YT Channel",
            },
        )
        stream_id = create_data["id"]

        # Act — update its display_name
        status, data = _json_request(
            conn,
            "PATCH",
            f"/api/v1/streams/{stream_id}",
            {"display_name": "Renamed"},
        )
        assert status == 200
        assert data == {"status": "updated"}

        # Assert — list reflects the change
        _, list_data = _json_request(conn, "GET", "/api/v1/streams")
        assert list_data["items"][0]["display_name"] == "Renamed"

    def test_dashboard_state_empty(self, conn: HTTPConnection) -> None:
        status, data = _json_request(conn, "GET", "/api/v1/dashboard/state")
        assert status == 200
        assert data["total_count"] == 0
        assert data["streams"] == []

    def test_dashboard_state_reflects_data(self, conn: HTTPConnection) -> None:
        # Insert a stream via the handler directly (setup)
        container = APIHandler.container
        container.add_stream_handler.handle(
            AddStreamCommand(
                platform="twitch",
                handle="dash_user",
                source_url="https://twitch.tv/dash_user",
                display_name="Dashboard User",
            )
        )

        status, data = _json_request(conn, "GET", "/api/v1/dashboard/state")
        assert status == 200
        assert data["total_count"] == 1
        assert data["live_count"] == 0
        assert data["streams"][0]["handle"] == "dash_user"

    def test_404_on_unknown_route(self, conn: HTTPConnection) -> None:
        status, data = _json_request(conn, "GET", "/api/v1/nonexistent")
        assert status == 404
        assert data["error"]["code"] == "not_found"

    def test_404_on_unknown_method(self, conn: HTTPConnection) -> None:
        status, data = _json_request(conn, "DELETE", "/api/v1/streams")
        assert status == 404
        assert data["error"]["code"] == "not_found"

    def test_400_on_missing_required_fields(self, conn: HTTPConnection) -> None:
        body = {"platform": "twitch"}  # missing handle, source_url, display_name

        status, data = _json_request(conn, "POST", "/api/v1/streams", body)
        assert status == 400
        assert data["error"]["code"] == "bad_request"

    def test_400_on_empty_post_body(self, conn: HTTPConnection) -> None:
        headers = {"Content-Type": "application/json"}
        conn.request("POST", "/api/v1/streams", body=b"", headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert resp.status == 400
        assert data["error"]["code"] == "bad_request"

    def test_400_on_invalid_json(self, conn: HTTPConnection) -> None:
        headers = {"Content-Type": "application/json"}
        conn.request("POST", "/api/v1/streams", body=b"not json", headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert resp.status == 400
        assert data["error"]["code"] == "bad_request"

    def test_400_on_update_without_body(self, conn: HTTPConnection) -> None:
        headers = {"Content-Type": "application/json"}
        conn.request("PATCH", "/api/v1/streams/fake-id", body=b"", headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert resp.status == 400
        assert data["error"]["code"] == "bad_request"

    def test_400_on_update_missing_entity(self, conn: HTTPConnection) -> None:
        body = {"display_name": "Ghost"}

        status, data = _json_request(
            conn, "PATCH", "/api/v1/streams/nonexistent", body
        )
        assert status == 400
        assert "not found" in data["error"]["message"]

    # ── disable / enable monitoring ─────────────────────────────────

    def test_disable_monitoring(self, conn: HTTPConnection) -> None:
        # Arrange — create a stream
        _, create_data = _json_request(
            conn,
            "POST",
            "/api/v1/streams",
            {
                "platform": "twitch",
                "handle": "disable_me",
                "source_url": "https://twitch.tv/disable_me",
                "display_name": "Disable Me",
            },
        )
        stream_id = create_data["id"]

        # Act — disable
        status, data = _json_request(
            conn, "POST", f"/api/v1/streams/{stream_id}/disable-monitoring"
        )
        assert status == 200
        assert data == {"status": "disabled"}

        # Assert — list reflects the change
        _, list_data = _json_request(conn, "GET", "/api/v1/streams")
        item = next(i for i in list_data["items"] if i["id"] == stream_id)
        assert item["enabled"] is False

    def test_enable_monitoring(self, conn: HTTPConnection) -> None:
        # Arrange — create a stream then disable it
        _, create_data = _json_request(
            conn,
            "POST",
            "/api/v1/streams",
            {
                "platform": "twitch",
                "handle": "enable_me",
                "source_url": "https://twitch.tv/enable_me",
                "display_name": "Enable Me",
            },
        )
        stream_id = create_data["id"]

        _json_request(
            conn, "POST", f"/api/v1/streams/{stream_id}/disable-monitoring"
        )

        # Act — enable
        status, data = _json_request(
            conn, "POST", f"/api/v1/streams/{stream_id}/enable-monitoring"
        )
        assert status == 200
        assert data == {"status": "enabled"}

        # Assert — list reflects the change
        _, list_data = _json_request(conn, "GET", "/api/v1/streams")
        item = next(i for i in list_data["items"] if i["id"] == stream_id)
        assert item["enabled"] is True

    def test_disable_monitoring_404_on_missing(self, conn: HTTPConnection) -> None:
        status, data = _json_request(
            conn, "POST", "/api/v1/streams/nonexistent/disable-monitoring"
        )
        assert status == 400
        assert "not found" in data["error"]["message"]

    def test_enable_monitoring_404_on_missing(self, conn: HTTPConnection) -> None:
        status, data = _json_request(
            conn, "POST", "/api/v1/streams/nonexistent/enable-monitoring"
        )
        assert status == 400
        assert "not found" in data["error"]["message"]

    # ── force-check ────────────────────────────────────────────────

    def test_force_check_returns_result_for_existing_stream(
        self, conn: HTTPConnection
    ) -> None:
        # Arrange — create a stream first
        _, create_data = _json_request(
            conn,
            "POST",
            "/api/v1/streams",
            {
                "platform": "tiktok",
                "handle": "checktarget",
                "source_url": "https://www.tiktok.com/@checktarget/live",
                "display_name": "Check Target",
            },
        )
        stream_id = create_data["id"]

        # Act — force-check
        status, data = _json_request(
            conn, "POST", f"/api/v1/streams/{stream_id}/force-check"
        )

        # Assert — the mocked resolver returns is_live=False
        assert status == 200
        assert data["stream_id"] == stream_id
        assert data["is_live"] is False
        # Other fields may be None since the mock returns defaults
        assert "stream_url" in data
        assert "title" in data
        assert "anchor_name" in data
        assert "m3u8_url" in data

    def test_force_check_404_on_missing_stream(
        self, conn: HTTPConnection
    ) -> None:
        status, data = _json_request(
            conn, "POST", "/api/v1/streams/nonexistent/force-check"
        )
        assert status == 400
        assert data["error"]["code"] == "bad_request"
        assert "not found" in data["error"]["message"]

    # ── favorite / unfavorite ───────────────────────────────────────

    def test_mark_favorite(self, conn: HTTPConnection) -> None:
        _, create_data = _json_request(
            conn,
            "POST",
            "/api/v1/streams",
            {
                "platform": "twitch",
                "handle": "fav_user",
                "source_url": "https://twitch.tv/fav_user",
                "display_name": "Favorite User",
            },
        )
        stream_id = create_data["id"]

        status, data = _json_request(
            conn, "POST", f"/api/v1/streams/{stream_id}/favorite"
        )
        assert status == 200
        assert data == {"status": "favorited"}

        _, list_data = _json_request(conn, "GET", "/api/v1/streams")
        item = next(i for i in list_data["items"] if i["id"] == stream_id)
        assert item["favorite"] is True

    def test_unmark_favorite(self, conn: HTTPConnection) -> None:
        _, create_data = _json_request(
            conn,
            "POST",
            "/api/v1/streams",
            {
                "platform": "twitch",
                "handle": "unfav_user",
                "source_url": "https://twitch.tv/unfav_user",
                "display_name": "Unfavorite User",
            },
        )
        stream_id = create_data["id"]

        # Mark it first
        _json_request(conn, "POST", f"/api/v1/streams/{stream_id}/favorite")

        # Then unmark
        status, data = _json_request(
            conn, "DELETE", f"/api/v1/streams/{stream_id}/favorite"
        )
        assert status == 200
        assert data == {"status": "unfavorited"}

        _, list_data = _json_request(conn, "GET", "/api/v1/streams")
        item = next(i for i in list_data["items"] if i["id"] == stream_id)
        assert item["favorite"] is False

    def test_mark_favorite_404_on_missing(self, conn: HTTPConnection) -> None:
        status, data = _json_request(
            conn, "POST", "/api/v1/streams/nonexistent/favorite"
        )
        assert status == 400
        assert "not found" in data["error"]["message"]

    def test_unmark_favorite_404_on_missing(self, conn: HTTPConnection) -> None:
        status, data = _json_request(
            conn, "DELETE", f"/api/v1/streams/nonexistent/favorite"
        )
        assert status == 400
        assert "not found" in data["error"]["message"]

    # ── recordings ─────────────────────────────────────────────────

    def _seed_recording(self, container: Container, **overrides) -> str:
        """Insert a recording session directly via the repo and return its id.

        Ensures the referenced stream target exists in the database first
        (FK constraint requirement).  Terminal sessions automatically get
        their ``ended_at`` set to ``now`` if none is provided.
        """
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import (
            Platform,
            QueueBand,
            RecordingStatus,
            utc_now,
        )
        from app.domain.stream_target.entities import StreamTarget
        from app.domain.stream_target.value_objects import ScheduleMode

        stream_target_id = overrides.get("stream_target_id", "target-1")

        # Ensure the referenced stream target exists
        if container.stream_target_repo.get(stream_target_id) is None:
            now = utc_now()
            target = StreamTarget(
                id=stream_target_id,
                platform=overrides.get("source_platform", Platform.TWITCH),
                handle=stream_target_id,
                source_url="https://example.com",
                display_name=f"Target {stream_target_id}",
                enabled=True,
                favorite=False,
                preferred_quality=None,
                output_profile_id=None,
                schedule_mode=ScheduleMode.NONE,
                created_at=now,
                updated_at=now,
            )
            container.stream_target_repo.save(target)

        now = utc_now()
        status = overrides.get("status", RecordingStatus.COMPLETED)
        ended_at = overrides.get("ended_at", ...)

        # Terminal sessions must have an ended_at
        is_terminal = status in (
            RecordingStatus.COMPLETED,
            RecordingStatus.FAILED,
            RecordingStatus.ABORTED,
            RecordingStatus.SPLIT,
        )
        if ended_at is ... and is_terminal:
            ended_at = now
        elif ended_at is ...:
            ended_at = None

        session = RecordingSession(
            id=overrides.get("id", f"rec-{hash(str(overrides))}"),
            stream_target_id=stream_target_id,
            started_at=overrides.get("started_at", now),
            ended_at=ended_at,
            status=status,
            source_platform=overrides.get("source_platform", Platform.TWITCH),
            stream_title=overrides.get("stream_title", None),
            detected_by_queue=overrides.get("detected_by_queue", QueueBand.FAST),
            detection_latency_seconds=overrides.get("detection_latency_seconds", 5.0),
            scheduled_hint_delay_minutes=overrides.get(
                "scheduled_hint_delay_minutes", None
            ),
            split_reason=overrides.get("split_reason", None),
            error_code=overrides.get("error_code", None),
            error_message=overrides.get("error_message", None),
            created_at=overrides.get("created_at", now),
            updated_at=overrides.get("updated_at", now),
        )
        container.recording_session_repo.save(session)
        return session.id

    def test_get_recordings_empty(self, conn: HTTPConnection) -> None:
        status, data = _json_request(conn, "GET", "/api/v1/recordings")
        assert status == 200
        assert data == {"items": []}

    def test_get_recordings_returns_sessions(self, conn: HTTPConnection) -> None:
        container = APIHandler.container
        self._seed_recording(container, id="rec-1", stream_target_id="t1")
        self._seed_recording(container, id="rec-2", stream_target_id="t2")

        status, data = _json_request(conn, "GET", "/api/v1/recordings")
        assert status == 200
        assert len(data["items"]) == 2
        ids = {i["id"] for i in data["items"]}
        assert ids == {"rec-1", "rec-2"}

    def test_get_recordings_filters_by_stream_id(self, conn: HTTPConnection) -> None:
        container = APIHandler.container
        self._seed_recording(container, id="r1", stream_target_id="t1")
        self._seed_recording(container, id="r2", stream_target_id="t2")

        status, data = _json_request(
            conn, "GET", "/api/v1/recordings?stream_id=t1"
        )
        assert status == 200
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "r1"

    def test_get_recordings_contains_expected_fields(
        self, conn: HTTPConnection
    ) -> None:
        from app.domain.shared.types import RecordingStatus

        container = APIHandler.container
        self._seed_recording(
            container,
            id="rec-fields",
            stream_target_id="t1",
            stream_title="Test Stream",
            status=RecordingStatus.RECORDING,
        )

        status, data = _json_request(conn, "GET", "/api/v1/recordings")
        assert status == 200
        item = data["items"][0]

        assert item["id"] == "rec-fields"
        assert item["stream_target_id"] == "t1"
        assert item["status"] == "recording"
        assert item["source_platform"] == "twitch"
        assert item["stream_title"] == "Test Stream"
        assert item["detected_by_queue"] == "fast"
        assert item["started_at"] is not None
        assert item["created_at"] is not None
        assert item["updated_at"] is not None
        # Optional fields — should be null for active recording
        assert item["ended_at"] is None
        assert item["duration_seconds"] is None
        assert item["error_code"] is None
        assert item["error_message"] is None
        assert item["split_reason"] is None

    # ── Cookies ────────────────────────────────────────────────────

    def test_list_cookies_empty(self, conn: HTTPConnection) -> None:
        status, data = _json_request(conn, "GET", "/api/v1/cookies")
        assert status == 200
        assert data == {"platforms": []}

    def test_get_cookie_platform_empty(self, conn: HTTPConnection) -> None:
        status, data = _json_request(
            conn, "GET", "/api/v1/cookies/nonexistent"
        )
        assert status == 200
        assert data == {
            "platform": "nonexistent",
            "cookie_string": "",
            "has_cookies": False,
        }

    def test_import_and_list_cookies(
        self, conn: HTTPConnection, tmp_path
    ) -> None:
        # Arrange — write a Puppeteer-style JSON export file
        cookie_file = tmp_path / "export.json"
        cookie_file.write_text(json.dumps(SAMPLE_PUPPETEER_JSON))

        # Act — import
        status, data = _json_request(
            conn,
            "POST",
            "/api/v1/cookies/import",
            {"platform": "twitch", "file_path": str(cookie_file)},
        )
        assert status == 200
        assert data == {
            "status": "imported",
            "platform": "twitch",
            "count": 3,
        }

        # Assert — list now includes twitch
        status, data = _json_request(conn, "GET", "/api/v1/cookies")
        assert data == {"platforms": ["twitch"]}

    def test_get_cookie_platform_after_import(
        self, conn: HTTPConnection, tmp_path
    ) -> None:
        # Arrange — seed cookies via import
        cookie_file = tmp_path / "export.json"
        cookie_file.write_text(json.dumps(SAMPLE_PUPPETEER_JSON))
        _json_request(
            conn,
            "POST",
            "/api/v1/cookies/import",
            {"platform": "twitch", "file_path": str(cookie_file)},
        )

        # Act — get platform
        status, data = _json_request(
            conn, "GET", "/api/v1/cookies/twitch"
        )
        assert status == 200
        assert data["platform"] == "twitch"
        assert data["has_cookies"] is True
        assert "sessionid=abc123" in data["cookie_string"]
        assert "persistent=xyz789" in data["cookie_string"]

    def test_set_cookie_via_api(self, conn: HTTPConnection) -> None:
        # Act — set a single cookie
        status, data = _json_request(
            conn,
            "POST",
            "/api/v1/cookies/youtube",
            {"name": "SESSION", "value": "xyz789"},
        )
        assert status == 200
        assert data == {
            "status": "set",
            "platform": "youtube",
            "name": "SESSION",
        }

        # Assert — read it back
        status, data = _json_request(
            conn, "GET", "/api/v1/cookies/youtube"
        )
        assert data["cookie_string"] == "SESSION=xyz789"
        assert data["has_cookies"] is True

    def test_set_cookie_updates_existing(
        self, conn: HTTPConnection
    ) -> None:
        # Set initial value
        _json_request(
            conn,
            "POST",
            "/api/v1/cookies/twitch",
            {"name": "session", "value": "first"},
        )
        # Update it
        status, data = _json_request(
            conn,
            "POST",
            "/api/v1/cookies/twitch",
            {"name": "session", "value": "updated"},
        )
        assert status == 200

        # Verify update
        _, data = _json_request(conn, "GET", "/api/v1/cookies/twitch")
        assert data["cookie_string"] == "session=updated"

    def test_import_nonexistent_file_returns_400(
        self, conn: HTTPConnection
    ) -> None:
        status, data = _json_request(
            conn,
            "POST",
            "/api/v1/cookies/import",
            {"platform": "twitch", "file_path": "/nonexistent/file.json"},
        )
        assert status == 400
        assert data["error"]["code"] == "bad_request"

    def test_import_missing_fields_returns_400(
        self, conn: HTTPConnection
    ) -> None:
        status, data = _json_request(
            conn,
            "POST",
            "/api/v1/cookies/import",
            {"platform": "twitch"},  # missing file_path
        )
        assert status == 400
        assert data["error"]["code"] == "bad_request"

    def test_set_cookie_missing_fields_returns_400(
        self, conn: HTTPConnection
    ) -> None:
        status, data = _json_request(
            conn,
            "POST",
            "/api/v1/cookies/twitch",
            {"name": "only_name"},  # missing value
        )
        assert status == 400
        assert data["error"]["code"] == "bad_request"
