"""PredictionResult — the unified output of the prediction engine.

Every consumer (scheduler, UI) reads from this single structure.

Invariants:
    - likelihood is always in [0.0, 1.0].
    - confidence is a valid Confidence level.
    - ui_state is a valid UiState value.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.shared.types import Confidence, UiState


@dataclass
class PredictionResult:
    """Unified prediction output for one stream target."""

    likelihood: float  # 0.0 – 1.0
    confidence: Confidence
    predicted_window_start: datetime | None
    predicted_window_end: datetime | None
    next_slot_at: datetime | None
    ui_state: UiState
    reasons: list[str] = field(default_factory=list)

    # ── Invariants ───────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not 0.0 <= self.likelihood <= 1.0:
            raise ValueError(
                f"likelihood must be in [0.0, 1.0], got {self.likelihood}"
            )

    # ── Derived state helpers ────────────────────────────────────────

    @property
    def is_expecting_live(self) -> bool:
        """Whether the engine expects a live stream in the near window."""
        return self.ui_state in (
            UiState.UPCOMING,
            UiState.EXPECTED_NOW,
            UiState.DELAYED,
        )

    @property
    def is_cold(self) -> bool:
        """Whether the target has no recent or predictable activity."""
        return self.ui_state == UiState.COLD

    @property
    def is_disabled(self) -> bool:
        """Whether the target is disabled (not being monitored)."""
        return self.ui_state == UiState.DISABLED

    @property
    def window_duration_minutes(self) -> float | None:
        """Duration of the predicted window in minutes, if both bounds are set."""
        if self.predicted_window_start and self.predicted_window_end:
            delta = self.predicted_window_end - self.predicted_window_start
            return delta.total_seconds() / 60.0
        return None
