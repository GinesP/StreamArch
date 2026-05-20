"""PredictionFeatures — partial signals that feed the unified engine.

Each feature computes one aspect of the likelihood estimate.
These are consumed by PredictionEngine, never exposed directly.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PredictionFeatures:
    hourly_pattern_score: float
    session_pattern_score: float
    schedule_hint_score: float
    recency_factor: float
    consistency_factor: float
    ema_priority: float
    favorite_bias: float
    computed_at: datetime
