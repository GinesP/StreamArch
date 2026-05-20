"""WebSocket event handler — broadcasts domain events to connected UI clients.

Endpoint: /ws/events

Envelope format:
    {"seq": int, "type": str, "timestamp": str, "payload": {}}

Event types:
    stream.status_changed
    stream.forecast_updated
    recording.started
    recording.progress
    recording.finished
    postprocess.updated
    queue.health_updated
    system.alert
"""


class WebSocketHandler:
    def broadcast(self, event_type: str, payload: dict) -> None:
        raise NotImplementedError

    def get_current_sequence(self) -> int:
        raise NotImplementedError
