"""PredictionService — coordinates PredictionEngine with data access.

Loads historical signals, calls the engine, and persists results.
"""


class PredictionService:
    def refresh_prediction(self, stream_target_id: str) -> None:
        """Recompute and persist prediction for a single target."""
        raise NotImplementedError
