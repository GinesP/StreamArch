"""Data transfer objects for stream target operations."""

from dataclasses import dataclass


# ── Combined overview (target + snapshot) ──────────────────────────────

@dataclass
class StreamOverviewDTO:
    """A stream target with its current monitoring snapshot, for list views.

    This is the primary read model for presenting stream targets in
    dashboards, API responses, and WebSocket payloads.
    """

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


# ── Detail views ───────────────────────────────────────────────────────

@dataclass
class StreamDetailDTO:
    """Full stream target details — all entity fields, no snapshot data."""

    id: str
    platform: str
    handle: str
    source_url: str
    display_name: str
    enabled: bool
    favorite: bool
    preferred_quality: str | None
    output_profile_id: str | None
    schedule_mode: str
    created_at: str
    updated_at: str


@dataclass
class StreamSnapshotDTO:
    """Current monitoring snapshot for one stream target."""

    stream_target_id: str
    state: str
    queue_band: str | None
    current_likelihood: float
    current_confidence: str
    next_check_at: str | None
    last_checked_at: str | None
    last_live_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    updated_at: str


# ── Aggregates ─────────────────────────────────────────────────────────

@dataclass
class DashboardStateDTO:
    """Aggregate dashboard combining all targets with current snapshots."""

    streams: list[StreamOverviewDTO]
    total_count: int
    live_count: int
    error_count: int
    idle_count: int


# ── Forecast (kept from earlier design) ────────────────────────────────

@dataclass
class ForecastDTO:
    """Prediction forecast for a stream target."""

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


# ── Alias for backward compat (used by presenters) ────────────────────

StreamTargetDTO = StreamOverviewDTO
