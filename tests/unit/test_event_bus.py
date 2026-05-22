"""Tests for EventBus — thread-safe publish/subscribe for in-process events."""

import logging
import threading
from typing import Any

import pytest

from app.infrastructure.events.event_bus import EventBus


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


# ── Subscribe / Publish basics ───────────────────────────────────────────


class TestSubscribePublish:
    def test_publish_delivers_to_subscriber(self, bus: EventBus) -> None:
        received: list[tuple[str, dict]] = []

        def cb(topic: str, payload: dict) -> None:
            received.append((topic, payload))

        bus.subscribe("test.event", cb)
        bus.publish("test.event", {"key": "value"})

        assert len(received) == 1
        assert received[0] == ("test.event", {"key": "value"})

    def test_publish_to_no_subscribers_is_noop(self, bus: EventBus) -> None:
        bus.publish("nonexistent", {"data": 1})  # Should not raise

    def test_publish_delivers_to_all_subscribers(self, bus: EventBus) -> None:
        results: list[int] = []

        def cb1(topic: str, payload: dict) -> None:
            results.append(1)

        def cb2(topic: str, payload: dict) -> None:
            results.append(2)

        bus.subscribe("test.event", cb1)
        bus.subscribe("test.event", cb2)
        bus.publish("test.event", {})

        assert sorted(results) == [1, 2]

    def test_multiple_topics_isolated(self, bus: EventBus) -> None:
        received_a: list[str] = []
        received_b: list[str] = []

        def cb_a(t: str, p: dict) -> None:
            received_a.append(t)

        def cb_b(t: str, p: dict) -> None:
            received_b.append(t)

        bus.subscribe("topic.a", cb_a)
        bus.subscribe("topic.b", cb_b)

        bus.publish("topic.a", {})
        bus.publish("topic.b", {})

        assert received_a == ["topic.a"]
        assert received_b == ["topic.b"]

    def test_payload_passed_unchanged(self, bus: EventBus) -> None:
        received: dict | None = None

        def cb(t: str, p: dict) -> None:
            nonlocal received
            received = p

        original = {"nested": {"value": 42}, "list": [1, 2, 3]}
        bus.subscribe("test", cb)
        bus.publish("test", original)

        assert received == original
        # Should be the same object, not a copy
        assert received is original


# ── Unsubscribe ──────────────────────────────────────────────────────────


class TestUnsubscribe:
    def test_unsubscribe_removes_callback(self, bus: EventBus) -> None:
        count = 0

        def cb(t: str, p: dict) -> None:
            nonlocal count
            count += 1

        bus.subscribe("test", cb)
        bus.publish("test", {})
        assert count == 1

        bus.unsubscribe("test", cb)
        bus.publish("test", {})
        assert count == 1  # Unchanged

    def test_unsubscribe_nonexistent_is_noop(self, bus: EventBus) -> None:
        def cb(t: str, p: dict) -> None:
            pass

        bus.unsubscribe("nonexistent", cb)  # Should not raise
        bus.unsubscribe("test", cb)  # Not subscribed — should not raise

    def test_unsubscribe_does_not_affect_other_callbacks(self, bus: EventBus) -> None:
        results: list[str] = []

        def cb1(t: str, p: dict) -> None:
            results.append("cb1")

        def cb2(t: str, p: dict) -> None:
            results.append("cb2")

        bus.subscribe("test", cb1)
        bus.subscribe("test", cb2)

        bus.unsubscribe("test", cb1)
        bus.publish("test", {})

        assert results == ["cb2"]

    def test_subscribe_same_callback_twice(self, bus: EventBus) -> None:
        count = 0

        def cb(t: str, p: dict) -> None:
            nonlocal count
            count += 1

        bus.subscribe("test", cb)
        bus.subscribe("test", cb)
        bus.publish("test", {})

        assert count == 2  # Called once per registration


# ── Error handling ───────────────────────────────────────────────────────


class TestErrorHandling:
    def test_subscriber_exception_does_not_break_bus(self, bus: EventBus, caplog: pytest.LogCaptureFixture) -> None:
        """A raising subscriber should not prevent other subscribers from
        receiving the event."""
        results: list[str] = []

        def failing_cb(t: str, p: dict) -> None:
            raise ValueError("oops")

        def good_cb(t: str, p: dict) -> None:
            results.append("ok")

        with caplog.at_level(logging.ERROR):
            bus.subscribe("test", failing_cb)
            bus.subscribe("test", good_cb)
            bus.publish("test", {})

        assert results == ["ok"]
        assert any("EventBus subscriber raised" in record.message for record in caplog.records)


# ── Introspection ────────────────────────────────────────────────────────


class TestIntrospection:
    def test_subscriber_count(self, bus: EventBus) -> None:
        assert bus.subscriber_count("test") == 0

        def cb(t: str, p: dict) -> None:
            pass

        bus.subscribe("test", cb)
        assert bus.subscriber_count("test") == 1

        bus.subscribe("test", cb)
        assert bus.subscriber_count("test") == 2

        bus.unsubscribe("test", cb)
        assert bus.subscriber_count("test") == 0

    def test_topics_property(self, bus: EventBus) -> None:
        assert bus.topics == []

        def cb(t: str, p: dict) -> None:
            pass

        bus.subscribe("topic.a", cb)
        bus.subscribe("topic.b", cb)
        assert sorted(bus.topics) == ["topic.a", "topic.b"]


# ── Thread safety ────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_publish(self, bus: EventBus) -> None:
        """Multiple threads can publish simultaneously without corruption."""
        n = 100
        received: list[int] = []
        lock = threading.Lock()

        def cb(t: str, p: dict) -> None:
            with lock:
                received.append(p["idx"])

        bus.subscribe("test", cb)

        def publisher(start: int) -> None:
            for i in range(start, start + n):
                bus.publish("test", {"idx": i})

        threads = [
            threading.Thread(target=publisher, args=(0,), daemon=True),
            threading.Thread(target=publisher, args=(n,), daemon=True),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(received) == n * 2
        assert len(set(received)) == n * 2  # No duplicates

    def test_concurrent_subscribe_unsubscribe(self, bus: EventBus) -> None:
        """Threads can subscribe/unsubscribe while publishing."""
        n = 50
        stop = threading.Event()

        def publisher() -> None:
            while not stop.is_set():
                bus.publish("test", {})

        def subscriber() -> None:
            def cb(t: str, p: dict) -> None:
                pass

            for _ in range(20):
                bus.subscribe("test", cb)
                bus.unsubscribe("test", cb)

        pub_thread = threading.Thread(target=publisher, daemon=True)
        sub_threads = [
            threading.Thread(target=subscriber, daemon=True) for _ in range(5)
        ]

        pub_thread.start()
        for t in sub_threads:
            t.start()

        # Let them run for a bit
        import time
        time.sleep(0.2)
        stop.set()

        pub_thread.join(timeout=2.0)
        for t in sub_threads:
            t.join(timeout=2.0)

        # No crash is the main assertion
        assert True
