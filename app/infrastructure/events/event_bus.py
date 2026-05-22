"""EventBus — thread-safe publish/subscribe for in-process event delivery.

Allows domain and application components to emit events without knowing
who consumes them.  The WebSocket server subscribes to all topics and
broadcasts to connected clients.
"""

import logging
import threading
from typing import Callable

CallableT = Callable[[str, dict], None]
"""Type alias for event bus callbacks: ``(topic, payload) -> None``."""

logger = logging.getLogger(__name__)


class EventBus:
    """Simple synchronous pub/sub event bus.

    Thread-safe: ``publish``, ``subscribe``, and ``unsubscribe`` can be
    called concurrently from any thread.

    Callbacks receive ``(topic: str, payload: dict)`` and are invoked
    **synchronously** in the publisher's thread.  If a callback raises,
    the exception is logged and other callbacks for the same topic still
    run.

    Usage::

        bus = EventBus()
        bus.subscribe("stream.status_changed", my_handler)
        bus.publish("stream.status_changed", {"stream_id": "st_1", "state": "recording"})
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[CallableT]] = {}
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────

    def subscribe(self, topic: str, callback: CallableT) -> None:
        """Register *callback* for events on *topic*.

        Multiple callbacks per topic are supported.  Registering the same
        callback twice results in two invocations per publish.

        Args:
            topic: Event topic string (e.g. ``"stream.status_changed"``).
            callback: Callable ``(topic, payload) -> None``.
        """
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: CallableT) -> None:
        """Remove *callback* from *topic*'s subscriber list.

        No-op if the topic or callback is not registered.

        Args:
            topic: Event topic string.
            callback: The same callable that was passed to ``subscribe``.
        """
        with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic] = [
                    cb for cb in self._subscribers[topic] if cb is not callback
                ]

    def publish(self, topic: str, payload: dict) -> None:
        """Deliver an event to all subscribers of *topic*.

        Subscribers are called synchronously in the current thread.  If
        any subscriber raises, the exception is caught and logged — other
        subscribers still receive the event.

        Args:
            topic: Event topic string.
            payload: Arbitrary JSON-serialisable dict payload.
        """
        callbacks: list[CallableT] = []
        with self._lock:
            if topic in self._subscribers:
                callbacks = list(self._subscribers[topic])

        for cb in callbacks:
            try:
                cb(topic, payload)
            except Exception:
                logger.exception(
                    "EventBus subscriber raised for topic=%s", topic,
                )

    # ── Introspection ────────────────────────────────────────────────

    def subscriber_count(self, topic: str) -> int:
        """Return the number of subscribers for *topic* (or 0)."""
        with self._lock:
            return len(self._subscribers.get(topic, []))

    @property
    def topics(self) -> list[str]:
        """List all topics that have at least one subscriber."""
        with self._lock:
            return list(self._subscribers.keys())
