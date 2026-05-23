"""WebSocket server — broadcasts domain events to connected UI clients.

Runs in a background thread with its own asyncio event loop.  Subscribes
to all relevant EventBus topics and broadcasts each event to every
connected WebSocket client using the envelope format defined in the
API contract.

Endpoint: /ws/events
"""

import asyncio
import json
import logging
import threading
from typing import Any

import websockets
from websockets import ServerConnection
from websockets.asyncio.server import Server
from websockets.frames import CloseCode

from app.domain.shared.types import utc_now
from app.infrastructure.events.event_bus import EventBus

# ── Event topics the server listens on ────────────────────────────────

EVENT_TOPICS: list[str] = [
    "stream.status_changed",
    "stream.forecast_updated",
    "recording.started",
    "recording.progress",
    "recording.finished",
    "postprocess.updated",
    "queue.health_updated",
    "queue.cycle_stats",
    "system.alert",
    "system.core_ready",
]
"""All event topics that the WebSocket server subscribes to."""

logger = logging.getLogger(__name__)


class WebSocketServer:
    """Broadcasts domain events to connected WebSocket clients.

    Runs in a daemon background thread with a dedicated asyncio event
    loop.  Subscribes to the ``EventBus`` on all ``EVENT_TOPICS`` and
    forwards each event in the standard envelope format.

    Parameters
    ----------
    host:
        Interface to bind on (default ``"127.0.0.1"``).
    port:
        Port to listen on (default ``8900``).
    event_bus:
        Shared ``EventBus`` instance to subscribe to.
    """

    def __init__(
        self,
        host: str,
        port: int,
        event_bus: EventBus,
    ) -> None:
        self._host = host
        self._port = port
        self._event_bus = event_bus

        # ── Client tracking (thread-safe via lock) ─────────────────
        self._clients: set[ServerConnection] = set()
        self._clients_lock = threading.Lock()

        # ── Sequence number (thread-safe via lock) ─────────────────
        self._seq: int = 0
        self._seq_lock = threading.Lock()

        # ── Lifecycle ──────────────────────────────────────────────
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Server | None = None

        # ── EventBus callback reference (stored to keep identity) ──
        # Bound-method access creates a new object each time, which
        # breaks unsubscribe's ``is`` comparison.  Storing it here
        # guarantees stable identity across subscribe / unsubscribe.
        self._event_callback = self._on_event

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the WebSocket server in a daemon background thread.

        Idempotent — subsequent calls are no-ops while already running.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("WebSocketServer is already running")
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            name="ws-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("WebSocketServer starting on %s:%s", self._host, self._port)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the server to stop and wait for the background thread.

        Calls ``Server.close()`` on the event loop, which causes
        ``serve_forever()`` to return, allowing the cleanup (including
        EventBus unsubscription) to execute before the thread exits.

        Args:
            timeout: Maximum seconds to wait for the thread to finish.
        """
        import time as _time
        deadline = _time.monotonic() + timeout

        if self._loop is not None and self._loop.is_running():
            if self._server is not None:
                self._loop.call_soon_threadsafe(self._do_close)

        if self._thread is not None and self._thread.is_alive():
            remaining = max(0.0, deadline - _time.monotonic())
            self._thread.join(timeout=remaining)
            if self._thread.is_alive():
                logger.warning(
                    "WebSocketServer thread did not stop within %ss", timeout,
                )
            else:
                logger.info("WebSocketServer stopped")

    def _do_close(self) -> None:
        """Callback scheduled on the event loop to close the server."""
        if self._server is not None:
            self._server.close()

    # ── Thread-safe broadcast ─────────────────────────────────────────

    def broadcast(self, message: str) -> None:
        """Send *message* to every connected client (thread-safe).

        This method may be called from any thread.  The actual send
        is scheduled on the server's asyncio event loop.
        """
        if self._loop is None or not self._loop.is_running():
            return

        async def _do_broadcast() -> None:
            await self._send_all(message)

        asyncio.run_coroutine_threadsafe(_do_broadcast(), self._loop)

    # ── Internal: asyncio loop runner ─────────────────────────────────

    def _run_loop(self) -> None:
        """Create and run the asyncio event loop for the WebSocket server."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve())
        except (Exception, asyncio.CancelledError):
            logger.exception("WebSocket server loop crashed")
        finally:
            # Cancel any remaining pending tasks gracefully.
            self._loop.run_until_complete(self._cancel_pending())
            self._loop.close()
            self._loop = None

    async def _cancel_pending(self) -> None:
        """Cancel all pending asyncio tasks during shutdown."""
        tasks = [
            t for t in asyncio.all_tasks(self._loop)
            if t is not asyncio.current_task()
        ]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _serve(self) -> None:
        """Start the WebSocket server and subscribe to EventBus topics.

        Uses ``server.serve_forever()`` which blocks until the server
        is closed (via ``stop()``), then unsubscribes from the event bus
        cleanly.
        """
        async with websockets.serve(
            self._handle_client,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
        ) as server:
            self._server = server

            # Subscribe to all event topics
            for topic in EVENT_TOPICS:
                self._event_bus.subscribe(topic, self._event_callback)

            logger.info(
                "WebSocket server ready on ws://%s:%s/ws/events",
                self._host,
                self._port,
            )

            # Block until stop() calls server.close()
            #
            # NOTE: server.close() → asyncio.Server.close() cancels
            # the internal _serving_forever_fut, which causes
            # serve_forever() to raise CancelledError.  We catch it
            # so that the unsubscription code below always runs.
            try:
                await server.serve_forever()
            except asyncio.CancelledError:
                pass

            # Unsubscribe from event bus (runs after close)
            for topic in EVENT_TOPICS:
                self._event_bus.unsubscribe(topic, self._event_callback)

            logger.info("WebSocket server shutting down")

    # ── Connection handler ────────────────────────────────────────────

    async def _handle_client(self, connection: ServerConnection) -> None:
        """Handle a single WebSocket client connection.

        Checks that the request path is ``/ws/events``, registers the
        client for broadcasts, then waits for the client to disconnect.
        """
        # Validate the request path
        if connection.request is not None and connection.request.path != "/ws/events":
            await connection.close(
                CloseCode.POLICY_VIOLATION,
                "Only /ws/events is supported",
            )
            return

        with self._clients_lock:
            self._clients.add(connection)
        logger.debug("WS client connected (%d total)", len(self._clients))

        try:
            # Keep the connection alive by waiting for messages we
            # never expect to receive (broadcast-only channel).
            async for _ in connection:
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            with self._clients_lock:
                self._clients.discard(connection)
            logger.debug(
                "WS client disconnected (%d remaining)", len(self._clients),
            )

    # ── EventBus callback (called from publisher thread) ──────────────

    def _on_event(self, topic: str, payload: dict) -> None:
        """Callback invoked by EventBus when an event is published.

        Builds the envelope and schedules a broadcast on the asyncio
        event loop.
        """
        envelope = self._build_envelope(topic, payload)
        message = json.dumps(envelope, default=str)

        if self._loop is not None and self._loop.is_running():
            async def _do_broadcast() -> None:
                await self._send_all(message)

            asyncio.run_coroutine_threadsafe(_do_broadcast(), self._loop)

    # ── Send to all clients ───────────────────────────────────────────

    async def _send_all(self, message: str) -> None:
        """Send *message* to every connected client.

        Disconnected clients are detected and silently removed.
        """
        with self._clients_lock:
            clients = set(self._clients)

        if not clients:
            return

        disconnected: set[ServerConnection] = set()
        for conn in clients:
            try:
                await conn.send(message)
            except websockets.ConnectionClosed:
                disconnected.add(conn)

        if disconnected:
            with self._clients_lock:
                self._clients -= disconnected

    # ── Envelope builder ──────────────────────────────────────────────

    def _next_seq(self) -> int:
        """Atomically increment and return the sequence number."""
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def _build_envelope(self, event_type: str, payload: dict) -> dict[str, Any]:
        """Build the standard WS envelope for an event.

        Returns a dict matching the contract::

            {"seq": int, "type": str, "timestamp": str, "payload": {...}}
        """
        return {
            "seq": self._next_seq(),
            "type": event_type,
            "timestamp": utc_now().isoformat(),
            "payload": payload,
        }

    # ── Introspection ────────────────────────────────────────────────

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        with self._clients_lock:
            return len(self._clients)

    @property
    def current_seq(self) -> int:
        """Current sequence number (last assigned)."""
        with self._seq_lock:
            return self._seq
