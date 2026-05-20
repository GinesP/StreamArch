"""PredictionEngine — unified prediction motor.

Produces a single coherent PredictionResult from all available signals.
This is the ONLY place where likelihood, window, and confidence are computed.
"""

from .features import PredictionFeatures
from .results import PredictionResult


class PredictionEngine:
    """Domain-level prediction engine.

    Responsibilities:
        - Combine hourly patterns, real sessions, manual hints, EMA,
          recency, consistency, and favorite bias.
        - Produce a unified likelihood, confidence, window, and ui_state.
        - Generate explainable reasons for every decision.
    """

    def predict(self, features: PredictionFeatures) -> PredictionResult:
        """Compute full prediction from aggregated features.

        This is a stub — actual signal combination comes later.
        """
        raise NotImplementedError
