"""Integration test for the full event flow.

Validates that:
1. EventBus delivers events synchronously to subscribers.
2. WebSocketServer subscribes to EventBus and broadcasts to clients.
3. The MonitoringCycle emits events when state transitions occur.

This test uses a lightweight, fast setup: a real EventBus + WebSocketServer
with real WebSocket connections, and a real MonitoringCycle wired with
mocked repositories and a real EventBus.
"""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import websockets

from app.application.orchestrators.monitoring_cycle import MonitoringCycle
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.prediction.engine import PredictionEngine
from app.domain.prediction.results import PredictionResult
from app.domain.shared.types import (
    Confidence,
    Platform,
    QueueBand,
    UiState,
)
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.events.event_bus import EventBus
from app.infrastructure.scheduler.queue_planner import QueuePlanner


# ── Helpers ──────────────────────────────────────────────────────────────


NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


def _target(**overrides) -> StreamTarget:
    return StreamTarget(
        id=overrides.get("id", "t1"),
        platform=overrides.get("platform", Platform.TWITCH),
        handle=overrides.get("handle", "streamer"),
        source_url=overrides.get("source_url", "https://twitch.tv/streamer"),
        display_name=overrides.get("display_name", "Streamer"),
        enabled=overrides.get("enabled", True),
        favorite=overrides.get("favorite", False),
        preferred_quality=overrides.get("preferred_quality", None),
        output_profile_id=overrides.get("output_profile_id", None),
        schedule_mode=overrides.get("schedule_mode", ScheduleMode.NONE),
        created_at=overrides.get("created_at", NOW),
        updated_at=overrides.get("updated_at", NOW),
    )


def _snapshot(**overrides) -> MonitoringSnapshot:
    return MonitoringSnapshot(
        stream_target_id=overrides.get("stream_target_id", "t1"),
        state=overrides.get("state", MonitoringState.IDLE),
        queue_band=overrides.get("queue_band", None),
        current_likelihood=overrides.get("current_likelihood", 0.0),
        current_confidence=overrides.get("current_confidence", Confidence.LOW),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", None),
        current_recording_session_id=overrides.get("current_recording_session_id", None),
        last_error_code=overrides.get("last_error_code", None),
        last_error_message=overrides.get("last_error_message", None),
        updated_at=overrides.get("updated_at", NOW),
    )


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Test: EventBus → WebSocket → Client ─────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_to_ws_to_client():
    """A full round-trip: EventBus.publish → WS server → WS client."""
    event_bus = EventBus()
    port = _free_port()

    # Import here to avoid circular issues in test discovery
    from app.interfaces.websocket.server import WebSocketServer

    server = WebSocketServer(
        host="127.0.0.1",
        port=port,
        event_bus=event_bus,
    )
    server.start()
    time.sleep(0.3)

    try:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws/events",
        ) as ws:
            await asyncio.sleep(0.2)

            # Publish an event via the bus
            event_bus.publish("stream.status_changed", {
                "stream_id": "st_1",
                "state": "recording",
                "queue_band": "fast",
                "likelihood": 1.0,
                "confidence": "high",
                "ui_state": "live",
            })

            # Receive it on the client
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg = json.loads(raw)

            assert msg["type"] == "stream.status_changed"
            assert msg["payload"]["stream_id"] == "st_1"
            assert msg["payload"]["state"] == "recording"
            assert msg["payload"]["queue_band"] == "fast"
            assert msg["seq"] >= 1
    finally:
        server.stop(timeout=3.0)


# ── Test: MonitoringCycle emits events via EventBus ──────────────────────


class TestMonitoringCycleEvents:
    """MonioringCycle detects state changes and emits events via EventBus.

    Uses real MonitoringCycle with mocked repositories and a real EventBus.
    """

    def test_emits_status_changed_on_state_transition(self) -> None:
        """When a target's state changes between cycles, a status_changed
        event is emitted.

        Uses a two-cycle approach: cycle 1 populates the internal cache
        (no event expected), cycle 2 detects the state change and emits.
        """
        event_bus = EventBus()
        received: list[dict] = []

        event_bus.subscribe("stream.status_changed", lambda t, p: received.append(p))

        # ── Set up mocks ──────────────────────────────────────────
        target = _target(id="t1")
        idle_every_call = _snapshot(
            stream_target_id="t1",
            state=MonitoringState.IDLE,
        )
        recording_every_call = _snapshot(
            stream_target_id="t1",
            state=MonitoringState.RECORDING,
            queue_band=QueueBand.FAST,
        )

        target_repo = MagicMock()
        target_repo.list_all.return_value = [target]

        snapshot_repo = MagicMock()
        # Always return the same snapshot for a given call
        snapshot_repo.get.side_effect = None  # reset
        snapshot_repo.get.return_value = recording_every_call

        session_repo = MagicMock()
        session_repo.list_by_target.return_value = []

        queue_planner = QueuePlanner()
        prediction_engine = MagicMock()
        prediction_engine.predict.return_value = PredictionResult(
            likelihood=0.5,
            confidence=Confidence.MEDIUM,
            predicted_window_start=None,
            predicted_window_end=None,
            next_slot_at=None,
            ui_state=UiState.IDLE,
            reasons=[],
        )

        cycle = MonitoringCycle(
            prediction_engine=prediction_engine,
            stream_target_repo=target_repo,
            monitoring_snapshot_repo=snapshot_repo,
            recording_session_repo=session_repo,
            queue_planner=queue_planner,
            logger=logging.getLogger(__name__),
            event_bus=event_bus,
            worker_pool=None,
        )

        # ── Cycle 1: populate cache ───────────────────────────────
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()
        assert len(received) == 0, "No event expected on first cycle"

        # ── Manually set the last known state to IDLE so cycle 2
        # sees a transition from IDLE → RECORDING.
        cycle._last_known_state["t1"] = MonitoringState.IDLE
        cycle._last_known_live["t1"] = False

        # ── Cycle 2: detect state change ──────────────────────────
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        assert len(received) == 1, f"Expected 1 event, got {len(received)}"
        payload = received[0]
        assert payload["stream_id"] == "t1"
        assert payload["state"] == "recording"
        assert payload["queue_band"] == "fast"

    def test_emits_status_changed_on_live_transition(self) -> None:
        """When the monitoring cycle detects a live stream (transition from
        not-live to live), it emits ``stream.status_changed``.

        Note: ``recording.started`` is now emitted by the ``RecordingService``,
        not by the monitoring cycle — this test only verifies the
        ``stream.status_changed`` event that the cycle still owns.
        """
        event_bus = EventBus()
        status_events: list[dict] = []
        recording_events: list[dict] = []

        event_bus.subscribe("stream.status_changed", lambda t, p: status_events.append(p))
        event_bus.subscribe("recording.started", lambda t, p: recording_events.append(p))

        target = _target(id="t1")
        recording_every_call = _snapshot(
            stream_target_id="t1",
            state=MonitoringState.RECORDING,
            queue_band=QueueBand.FAST,
            current_recording_session_id="rec_1",
        )

        target_repo = MagicMock()
        target_repo.list_all.return_value = [target]

        snapshot_repo = MagicMock()
        snapshot_repo.get.return_value = recording_every_call

        session_repo = MagicMock()
        session_repo.list_by_target.return_value = []

        queue_planner = QueuePlanner()
        prediction_engine = MagicMock()
        prediction_engine.predict.return_value = PredictionResult(
            likelihood=1.0,
            confidence=Confidence.HIGH,
            predicted_window_start=NOW,
            predicted_window_end=NOW,
            next_slot_at=NOW,
            ui_state=UiState.LIVE,
            reasons=["recent_live_activity"],
        )

        cycle = MonitoringCycle(
            prediction_engine=prediction_engine,
            stream_target_repo=target_repo,
            monitoring_snapshot_repo=snapshot_repo,
            recording_session_repo=session_repo,
            queue_planner=queue_planner,
            logger=logging.getLogger(__name__),
            event_bus=event_bus,
            worker_pool=None,
        )

        # Cycle 1: populate cache
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        # Manually set last known to IDLE
        cycle._last_known_state["t1"] = MonitoringState.IDLE
        cycle._last_known_live["t1"] = False

        # Cycle 2: detect becoming live
        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        assert len(status_events) == 1
        # recording.started is now emitted by RecordingService, not the cycle
        assert len(recording_events) == 0

    def test_emits_queue_health_every_cycle(self) -> None:
        """queue.health_updated is emitted every cycle, regardless of state
        changes."""
        event_bus = EventBus()
        received: list[dict] = []

        event_bus.subscribe("queue.health_updated", lambda t, p: received.append(p))

        target = _target(id="t1")
        snapshot = _snapshot(stream_target_id="t1")

        target_repo = MagicMock()
        target_repo.list_all.return_value = [target]

        snapshot_repo = MagicMock()
        snapshot_repo.get.return_value = snapshot

        session_repo = MagicMock()
        session_repo.list_by_target.return_value = []

        queue_planner = QueuePlanner()

        # Add some items to queue for depth
        queue_planner.enqueue("t1", QueueBand.FAST, "twitch")
        queue_planner.enqueue("t2", QueueBand.MEDIUM, "twitch")
        queue_planner.enqueue("t3", QueueBand.SLOW, "twitch")

        prediction_engine = MagicMock()
        prediction_engine.predict.return_value = PredictionResult(
            likelihood=0.0,
            confidence=Confidence.LOW,
            predicted_window_start=None,
            predicted_window_end=None,
            next_slot_at=None,
            ui_state=UiState.COLD,
            reasons=[],
        )

        cycle = MonitoringCycle(
            prediction_engine=prediction_engine,
            stream_target_repo=target_repo,
            monitoring_snapshot_repo=snapshot_repo,
            recording_session_repo=session_repo,
            queue_planner=queue_planner,
            logger=logging.getLogger(__name__),
            event_bus=event_bus,
            worker_pool=None,
        )

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        assert len(received) == 1
        payload = received[0]
        assert "fast" in payload
        assert "medium" in payload
        assert "slow" in payload
        # Queue depths we added
        assert payload["fast"]["depth"] >= 1
        assert payload["medium"]["depth"] >= 1
        assert payload["slow"]["depth"] >= 1
        # Worker counts default to 0 when no worker pool
        assert payload["fast"]["workers"] == 0

    def test_no_events_when_no_state_change(self) -> None:
        """When no state changes, only queue.health_updated is emitted (no
        status_changed)."""
        event_bus = EventBus()
        status_events: list[dict] = []

        event_bus.subscribe("stream.status_changed", lambda t, p: status_events.append(p))

        target = _target(id="t1")
        snapshot = _snapshot(
            stream_target_id="t1",
            state=MonitoringState.IDLE,
        )

        target_repo = MagicMock()
        target_repo.list_all.return_value = [target]

        snapshot_repo = MagicMock()
        snapshot_repo.get.return_value = snapshot  # Same state on both calls

        session_repo = MagicMock()
        session_repo.list_by_target.return_value = []

        queue_planner = QueuePlanner()
        prediction_engine = MagicMock()
        prediction_engine.predict.return_value = PredictionResult(
            likelihood=0.0,
            confidence=Confidence.LOW,
            predicted_window_start=None,
            predicted_window_end=None,
            next_slot_at=None,
            ui_state=UiState.COLD,
            reasons=[],
        )

        cycle = MonitoringCycle(
            prediction_engine=prediction_engine,
            stream_target_repo=target_repo,
            monitoring_snapshot_repo=snapshot_repo,
            recording_session_repo=session_repo,
            queue_planner=queue_planner,
            logger=logging.getLogger(__name__),
            event_bus=event_bus,
            worker_pool=None,
        )

        with patch(
            "app.application.orchestrators.monitoring_cycle.utc_now",
            return_value=NOW,
        ):
            cycle._run_one_cycle()

        # No status_changed since state was already IDLE
        assert len(status_events) == 0


# ── Test: Full end-to-end with MonitoringCycle ───────────────────────────


@pytest.mark.asyncio
async def test_monitoring_cycle_to_ws_client():
    """MonitoringCycle emits events → EventBus → WebSocketServer → client."""
    event_bus = EventBus()
    port = _free_port()

    from app.interfaces.websocket.server import WebSocketServer

    server = WebSocketServer(
        host="127.0.0.1",
        port=port,
        event_bus=event_bus,
    )
    server.start()
    time.sleep(0.3)

    try:
        # ── Set up a MonitoringCycle that detects a state change ──
        target = _target(id="t1")
        recording_snapshot = _snapshot(
            stream_target_id="t1",
            state=MonitoringState.RECORDING,
            queue_band=QueueBand.FAST,
        )

        target_repo = MagicMock()
        target_repo.list_all.return_value = [target]

        snapshot_repo = MagicMock()
        snapshot_repo.get.return_value = recording_snapshot

        session_repo = MagicMock()
        session_repo.list_by_target.return_value = []

        queue_planner = QueuePlanner()
        prediction_engine = MagicMock()
        prediction_engine.predict.return_value = PredictionResult(
            likelihood=1.0,
            confidence=Confidence.HIGH,
            predicted_window_start=NOW,
            predicted_window_end=NOW,
            next_slot_at=NOW,
            ui_state=UiState.LIVE,
            reasons=["recent_live_activity"],
        )

        cycle = MonitoringCycle(
            prediction_engine=prediction_engine,
            stream_target_repo=target_repo,
            monitoring_snapshot_repo=snapshot_repo,
            recording_session_repo=session_repo,
            queue_planner=queue_planner,
            logger=logging.getLogger(__name__),
            event_bus=event_bus,
            worker_pool=None,
        )

        # ── Pre-populate cache to simulate state transition ───────
        cycle._last_known_state["t1"] = MonitoringState.IDLE
        cycle._last_known_live["t1"] = False

        # ── Connect a WS client ──────────────────────────────────
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws/events",
        ) as ws:
            await asyncio.sleep(0.3)

            # ── Run the monitoring cycle ──────────────────────────
            with patch(
                "app.application.orchestrators.monitoring_cycle.utc_now",
                return_value=NOW,
            ):
                cycle._run_one_cycle()

            # ── Client should receive the event ───────────────────
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            msg = json.loads(raw)

            assert msg["type"] == "stream.status_changed"
            assert msg["payload"]["stream_id"] == "t1"
            assert msg["payload"]["state"] == "recording"
    finally:
        server.stop(timeout=3.0)
