"""PredictionEngine — unified prediction motor.

Takes raw domain objects (StreamTarget, MonitoringSnapshot) and produces
a single coherent PredictionResult.  All signal calculation is delegated
to ``features`` and ``policy`` so each concern can be tested in isolation.
"""

from datetime import datetime, timedelta

from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.shared.types import Confidence, UiState, utc_now
from app.domain.stream_target.entities import StreamTarget

from app.domain.prediction.explanations import (
    disabled_target,
    favorite_bias,
    recent_live_activity,
)
from app.domain.prediction.features import (
    BASELINE_MINIMUM,
    LIKELIHOOD_MEDIUM_THRESHOLD,
    calculate_consistency,
    calculate_ema,
    calculate_hourly_pattern,
    calculate_likelihood,
    calculate_recency_factor,
    calculate_session_pattern,
)
from app.domain.prediction.policy import get_adjusted_interval, get_interval_seconds
from app.domain.prediction.results import PredictionResult

# ── Confidence thresholds ───────────────────────────────────────────

CONFIDENCE_HIGH_THRESHOLD: float = 0.75
"""Likelihood at or above this → HIGH confidence."""

CONFIDENCE_MEDIUM_THRESHOLD: float = 0.45
"""Likelihood at or above this → MEDIUM confidence (else LOW)."""


class PredictionEngine:
    """Domain-level prediction engine.

    Responsibilities
    ----------------
    * Combine EMA, recency, consistency, hourly pattern, session
      pattern, and favourite bias into a unified likelihood score.
    * Map the score to a ``Confidence`` level, ``UiState``, and check
      interval.
    * Generate human-readable reasons for every decision.
    """

    def predict(
        self,
        stream_target: StreamTarget,
        snapshot: MonitoringSnapshot,
        previous_priority: float = 0.0,
        session_count: int = 0,
        sessions: list | None = None,
        live_check_count: int = 0,
        period_days: float = 30.0,
        *,
        _now: datetime | None = None,
    ) -> PredictionResult:
        """Compute a full prediction for *stream_target*.

        Parameters
        ----------
        stream_target
            The target being evaluated.
        snapshot
            Current operational state (latest known data).
        previous_priority
            The EMA priority from the previous run.  Pass 0.0 for new
            targets with no history.
        session_count
            Number of known recording sessions in the observation window.
        sessions
            Full list of recording sessions (used for hourly/session
            pattern analysis).
        live_check_count
            Number of times this target has been checked (used for
            deep-sleep detection).
        period_days
            Length of the observation window in days.
        _now
            Inject a fixed timestamp for testing.  Uses ``utc_now()``
            when ``None``.

        Returns
        -------
        PredictionResult
            A fully populated prediction with likelihood, confidence,
            UI state, predicted window, and reasons.
        """
        now = _now or utc_now()
        reasons: list[str] = []
        sessions_list = sessions or []

        # ── Disabled target ──────────────────────────────────────────
        if not stream_target.enabled:
            return PredictionResult(
                likelihood=0.0,
                confidence=Confidence.HIGH,
                predicted_window_start=None,
                predicted_window_end=None,
                next_slot_at=None,
                ui_state=UiState.DISABLED,
                reasons=[disabled_target()],
            )

        # ── Currently live ───────────────────────────────────────────
        if snapshot.is_live:
            return PredictionResult(
                likelihood=1.0,
                confidence=Confidence.HIGH,
                predicted_window_start=now,
                predicted_window_end=now,
                next_slot_at=now,
                ui_state=UiState.LIVE,
                reasons=[recent_live_activity()],
            )

        # ── Compute signals ──────────────────────────────────────────
        is_recording = snapshot.current_recording_session_id is not None
        ema = calculate_ema(previous_priority, is_live=False, is_recording=is_recording)
        recency = calculate_recency_factor(snapshot.last_live_at, now)
        consistency = calculate_consistency(session_count, period_days)
        hourly = calculate_hourly_pattern(sessions_list, now)
        session_pat = calculate_session_pattern(sessions_list, now)

        likelihood = calculate_likelihood(
            ema, recency, consistency, stream_target.favorite,
            hourly_pattern=hourly,
            session_pattern=session_pat,
        )

        # ── Reasons ──────────────────────────────────────────────────
        if stream_target.favorite and likelihood >= LIKELIHOOD_MEDIUM_THRESHOLD:
            reasons.append(favorite_bias())

        if snapshot.last_live_at is not None and recency > BASELINE_MINIMUM:
            reasons.append(recent_live_activity())

        # ── Confidence level ─────────────────────────────────────────
        confidence = self._classify_confidence(likelihood)

        # ── UI state ─────────────────────────────────────────────────
        ui_state = self._classify_ui_state(
            likelihood, stream_target.enabled, snapshot.is_live
        )

        # ── Interval & predicted window ──────────────────────────────
        interval = get_adjusted_interval(
            likelihood,
            previous_priority,
            stream_target.favorite,
            live_check_count=live_check_count,
        )

        if likelihood >= BASELINE_MINIMUM:
            predicted_window_start = now
            predicted_window_end = now + timedelta(seconds=interval)
            next_slot_at = now
        else:
            predicted_window_start = None
            predicted_window_end = None
            next_slot_at = None

        return PredictionResult(
            likelihood=round(likelihood, 4),
            confidence=confidence,
            predicted_window_start=predicted_window_start,
            predicted_window_end=predicted_window_end,
            next_slot_at=next_slot_at,
            ui_state=ui_state,
            reasons=reasons,
        )

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _classify_confidence(likelihood: float) -> Confidence:
        if likelihood >= CONFIDENCE_HIGH_THRESHOLD:
            return Confidence.HIGH
        if likelihood >= CONFIDENCE_MEDIUM_THRESHOLD:
            return Confidence.MEDIUM
        return Confidence.LOW

    @staticmethod
    def _classify_ui_state(
        likelihood: float,
        enabled: bool,
        is_live: bool,
    ) -> UiState:
        if not enabled:
            return UiState.DISABLED
        if is_live:
            return UiState.LIVE
        if likelihood >= LIKELIHOOD_MEDIUM_THRESHOLD:
            # >= 0.5 — expected in the near future
            if likelihood >= 0.9:
                return UiState.EXPECTED_NOW
            return UiState.UPCOMING
        if likelihood >= BASELINE_MINIMUM:
            return UiState.IDLE
        return UiState.COLD
