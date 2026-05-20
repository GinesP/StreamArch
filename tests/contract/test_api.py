"""Contract tests for the REST API.

Tests the HTTP surface directly — uses an in-memory SQLite database
and a real ``HTTPServer`` on a random local port.
"""

import json
import socket
import sqlite3
import threading
from http.client import HTTPConnection
from http.server import HTTPServer

import pytest

from app.application.commands.add_stream import AddStreamCommand, AddStreamHandler
from app.application.commands.update_stream import UpdateStreamHandler
from app.application.queries.get_dashboard_state import (
    GetDashboardStateHandler,
    GetDashboardStateQuery,
)
from app.application.queries.list_streams import ListStreamsHandler, ListStreamsQuery
from app.bootstrap.container import Container
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
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    return conn


@pytest.fixture
def container(db) -> Container:
    c = Container()
    c.stream_target_repo = StreamTargetRepository(db)
    c.monitoring_snapshot_repo = MonitoringSnapshotRepository(db)

    c.add_stream_handler = AddStreamHandler(
        stream_target_repo=c.stream_target_repo,
        monitoring_snapshot_repo=c.monitoring_snapshot_repo,
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
