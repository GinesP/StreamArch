"""PredictionResult — the unified output of the prediction engine.

Every consumer (scheduler, UI) reads from this single structure.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PredictionResult:
    likelihood: float       # 0.0 – 1.0
    confidence: str         # low | medium | high
    predicted_window_start: datetime | None
    predicted_window_end: datetime | None
    next_slot_at: datetime | None
    ui_state: str           # idle | upcoming | expected_now | delayed | live | cold | disabled
    reasons: list[str] = field(default_factory=list)
