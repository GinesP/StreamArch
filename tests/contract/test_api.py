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
from app.application.queries.list_streams import ListStreamsHandler, ListStreamsQuery
from app.bootstrap.container import Container
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.interfaces.api.routes import build_router
from app.interfaces.api.server import APIHandler, create_server

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
def container(db_path) -> Container:
    c = Container()
    c.stream_target_repo = StreamTargetRepository(db_path)
    c.monitoring_snapshot_repo = MonitoringSnapshotRepository(db_path)

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
            conn, "DELETE", "/api/v1/streams/nonexistent/favorite"
        )
        assert status == 400
        assert "not found" in data["error"]["message"]
