"""Data transfer objects for stream target operations."""

from dataclasses import dataclass


@dataclass
class StreamTargetDTO:
    id: str
    platform: str
    handle: str
    display_name: str
    enabled: bool
    favorite: bool
    state: str
    queue_band: str | None
    current_likelihood: float
    current_confidence: str
    next_check_at: str | None
    last_live_at: str | None


@dataclass
class ForecastDTO:
    stream_id: str
    likelihood: float
    confidence: str
    ui_state: str
    predicted_window: dict | None
    next_slot_at: str | None
    reasons: list[str]
    current_queue_band: str
    target_interval_seconds: int
    jittered_interval_seconds: int
