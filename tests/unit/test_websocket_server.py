"""Tests for WebSocketServer — broadcasts domain events to connected clients.

Uses the ``websockets`` sync client to connect to the test server,
verifying connect, disconnect, broadcast, and event delivery.
"""

import asyncio
import json
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import websockets
from websockets.protocol import State

from app.infrastructure.events.event_bus import EventBus
from app.interfaces.websocket.server import (
    EVENT_TOPICS,
    WebSocketServer,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def free_port() -> int:
    """Return a likely-free port for testing."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ws_server(event_bus: EventBus, free_port: int) -> WebSocketServer:
    server = WebSocketServer(
        host="127.0.0.1",
        port=free_port,
        event_bus=event_bus,
    )
    server.start()
    # Give the server a moment to start
    time.sleep(0.1)
    yield server
    server.stop(timeout=3.0)


# ── Helpers ──────────────────────────────────────────────────────────────


def _wait_for_condition(condition, timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Poll *condition* (a callable returning truthy) until it's met."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


# ── Server lifecycle ─────────────────────────────────────────────────────


class TestServerLifecycle:
    def test_start_stop(self, ws_server: WebSocketServer) -> None:
        """Server starts and stops without error."""
        assert ws_server._thread is not None
        assert ws_server._thread.is_alive()
        # Already started by fixture — just verify it's running

    def test_start_is_idempotent(self, ws_server: WebSocketServer) -> None:
        """Calling start() twice should not crash."""
        ws_server.start()  # Second call — should be no-op

    def test_subscribes_to_all_event_topics(self, event_bus: EventBus, free_port: int) -> None:
        """Server subscribes to all EVENT_TOPICS on the bus."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        for topic in EVENT_TOPICS:
            assert event_bus.subscriber_count(topic) == 1, f"Missing subscription: {topic}"

        server.stop()

    def test_unsubscribes_on_stop(self, event_bus: EventBus, free_port: int) -> None:
        """Server unsubscribes from all topics when stopped."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)
        server.stop(timeout=3.0)

        for topic in EVENT_TOPICS:
            assert event_bus.subscriber_count(topic) == 0, f"Still subscribed: {topic}"


# ── Client connect / disconnect ──────────────────────────────────────────


@pytest.mark.asyncio
class TestClientConnection:
    async def test_client_connects(self, free_port: int, event_bus: EventBus) -> None:
        """A client can connect to the WS server."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws:
                assert ws.state is State.OPEN
                # Handler registration may lag one event-loop tick
                assert _wait_for_condition(
                    lambda: server.client_count == 1, timeout=2.0,
                ), "Client was not registered on the server"
        finally:
            server.stop(timeout=3.0)

    async def test_client_disconnect(self, free_port: int, event_bus: EventBus) -> None:
        """Client count decreases after disconnect."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws:
                assert _wait_for_condition(
                    lambda: server.client_count == 1, timeout=2.0,
                ), "Client was not registered on the server"

            # After exiting the context manager, the connection is closed
            assert _wait_for_condition(lambda: server.client_count == 0, timeout=2.0)
        finally:
            server.stop(timeout=3.0)

    async def test_reject_wrong_path(self, free_port: int, event_bus: EventBus) -> None:
        """Connection to a path other than /ws/events is rejected.

        The server accepts the connection at the transport level and
        then the handler closes it with a policy-violation code, which
        manifests as ``ConnectionClosed`` on the client side.
        """
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            with pytest.raises(websockets.ConnectionClosed):
                async with websockets.connect(f"ws://127.0.0.1:{free_port}/wrong") as ws:
                    # The server should close us before we can receive
                    await ws.recv()
            assert server.client_count == 0
        finally:
            server.stop(timeout=3.0)

    async def test_multiple_clients(self, free_port: int, event_bus: EventBus) -> None:
        """Multiple clients can connect simultaneously."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with (
                websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws1,
                websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws2,
                websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws3,
            ):
                assert _wait_for_condition(
                    lambda: server.client_count == 3, timeout=2.0,
                )
        finally:
            server.stop(timeout=3.0)


# ── Broadcast ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestBroadcast:
    async def test_broadcast_to_single_client(
        self, free_port: int, event_bus: EventBus,
    ) -> None:
        """Event published on the bus is received by a connected client."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{free_port}/ws/events",
            ) as ws:
                # Wait for subscription to settle
                await asyncio.sleep(0.1)

                event_bus.publish("stream.status_changed", {
                    "stream_id": "st_1",
                    "state": "recording",
                })

                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(raw)

                assert msg["type"] == "stream.status_changed"
                assert msg["payload"]["stream_id"] == "st_1"
                assert isinstance(msg["seq"], int)
                assert isinstance(msg["timestamp"], str)
        finally:
            server.stop(timeout=3.0)

    async def test_broadcast_to_multiple_clients(
        self, free_port: int, event_bus: EventBus,
    ) -> None:
        """All connected clients receive the same broadcast."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with (
                websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws1,
                websockets.connect(f"ws://127.0.0.1:{free_port}/ws/events") as ws2,
            ):
                await asyncio.sleep(0.2)

                event_bus.publish("system.alert", {"message": "test"})

                raw1 = await asyncio.wait_for(ws1.recv(), timeout=3.0)
                raw2 = await asyncio.wait_for(ws2.recv(), timeout=3.0)
                msg1 = json.loads(raw1)
                msg2 = json.loads(raw2)

                assert msg1 == msg2
                assert msg1["type"] == "system.alert"
                assert msg1["payload"]["message"] == "test"
        finally:
            server.stop(timeout=3.0)

    async def test_event_envelope_format(
        self, free_port: int, event_bus: EventBus,
    ) -> None:
        """Each event follows the standard envelope: seq, type, timestamp, payload."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{free_port}/ws/events",
            ) as ws:
                await asyncio.sleep(0.1)

                event_bus.publish("queue.health_updated", {"fast": {"depth": 1}})

                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(raw)

                assert set(msg.keys()) == {"seq", "type", "timestamp", "payload"}
                assert isinstance(msg["seq"], int)
                assert isinstance(msg["type"], str)
                assert isinstance(msg["timestamp"], str)
                assert isinstance(msg["payload"], dict)
        finally:
            server.stop(timeout=3.0)

    async def test_seq_increments(
        self, free_port: int, event_bus: EventBus,
    ) -> None:
        """Seq number auto-increments with each event."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{free_port}/ws/events",
            ) as ws:
                await asyncio.sleep(0.1)

                event_bus.publish("queue.health_updated", {"n": 1})
                event_bus.publish("system.alert", {"n": 2})

                raw1 = await asyncio.wait_for(ws.recv(), timeout=3.0)
                raw2 = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg1 = json.loads(raw1)
                msg2 = json.loads(raw2)

                assert msg2["seq"] == msg1["seq"] + 1
        finally:
            server.stop(timeout=3.0)

    async def test_broadcast_string_method(
        self, free_port: int, event_bus: EventBus,
    ) -> None:
        """Calling broadcast() directly sends to all clients."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{free_port}/ws/events",
            ) as ws:
                await asyncio.sleep(0.1)

                server.broadcast('{"custom": true}')

                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                msg = json.loads(raw)
                assert msg["custom"] is True
        finally:
            server.stop(timeout=3.0)


# ── Disconnected client cleanup ──────────────────────────────────────────


@pytest.mark.asyncio
class TestDisconnectedClient:
    async def test_disconnected_client_removed(
        self, free_port: int, event_bus: EventBus,
    ) -> None:
        """Disconnected clients are removed from the set before the next send."""
        server = WebSocketServer(
            host="127.0.0.1",
            port=free_port,
            event_bus=event_bus,
        )
        server.start()
        time.sleep(0.2)

        try:
            # Connect a client, then let it disconnect by closing the socket
            async with websockets.connect(
                f"ws://127.0.0.1:{free_port}/ws/events",
            ) as ws:
                assert _wait_for_condition(
                    lambda: server.client_count == 1, timeout=2.0,
                )

            # After context manager exit, client should be gone
            assert _wait_for_condition(
                lambda: server.client_count == 0, timeout=2.0,
            )

            # Publishing after client disconnect should not raise
            event_bus.publish("test", {"after": "disconnect"})
            await asyncio.sleep(0.2)
        finally:
            server.stop(timeout=3.0)
