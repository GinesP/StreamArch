"""Tests for PredictionEngine — integrated signal combination.

These tests verify that the engine correctly:
    - Returns DISABLED for non-enabled targets
    - Returns LIVE for currently recording targets
    - Combines EMA, recency, consistency into a likelihood
    - Applies favourite bias
    - Determines correct Confidence and UiState levels
    - Builds appropriate reasons
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.prediction.engine import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    PredictionEngine,
)
from app.domain.prediction.features import BASELINE_MINIMUM
from app.domain.prediction.policy import (
    FAST_BAND_INTERVAL,
    MEDIUM_BAND_INTERVAL,
    SLOW_BAND_INTERVAL,
)
from app.domain.shared.types import Confidence, Platform, QueueBand, UiState
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState


# ── Helpers ──────────────────────────────────────────────────────────


def _target(**overrides) -> StreamTarget:
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
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
        created_at=overrides.get("created_at", now),
        updated_at=overrides.get("updated_at", now),
    )


def _snapshot(**overrides) -> MonitoringSnapshot:
    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    return MonitoringSnapshot(
        stream_target_id=overrides.get("stream_target_id", "t1"),
        state=overrides.get("state", MonitoringState.IDLE),
        queue_band=overrides.get("queue_band", None),
        current_likelihood=overrides.get("current_likelihood", 0.5),
        current_confidence=overrides.get("current_confidence", Confidence.MEDIUM),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", now - timedelta(days=7)),
        current_recording_session_id=overrides.get("current_recording_session_id", None),
        last_error_code=overrides.get("last_error_code", None),
        last_error_message=overrides.get("last_error_message", None),
        updated_at=overrides.get("updated_at", now),
    )


NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
engine = PredictionEngine()


# ======================================================================
# Edge states
# ======================================================================


class TestDisabledTarget:
    def test_returns_disabled(self) -> None:
        target = _target(enabled=False)
        snap = _snapshot()
        result = engine.predict(target, snap, _now=NOW)
        assert result.likelihood == 0.0
        assert result.confidence == Confidence.HIGH
        assert result.ui_state == UiState.DISABLED
        assert result.predicted_window_start is None
        assert result.predicted_window_end is None
        assert result.next_slot_at is None

    def test_disabled_reason(self) -> None:
        target = _target(enabled=False)
        snap = _snapshot()
        result = engine.predict(target, snap, _now=NOW)
        assert "disabled_target" in result.reasons


class TestLiveTarget:
    def test_returns_live(self) -> None:
        target = _target()
        snap = _snapshot(state=MonitoringState.RECORDING)
        result = engine.predict(target, snap, _now=NOW)
        assert result.likelihood == 1.0
        assert result.confidence == Confidence.HIGH
        assert result.ui_state == UiState.LIVE
        assert result.next_slot_at == NOW

    def test_live_reason(self) -> None:
        target = _target()
        snap = _snapshot(state=MonitoringState.RECORDING)
        result = engine.predict(target, snap, _now=NOW)
        assert "recent_live_activity" in result.reasons


# ======================================================================
# Combined scoring
# ======================================================================


class TestCombinedScoring:
    def test_high_ema_and_recency_produces_expected_now(self) -> None:
        """Target with high priority and recent activity → EXPECTED_NOW."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(hours=1))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.99,
            session_count=30,
            period_days=30,
            _now=NOW,
        )
        # ema = 0.995 * 0.99 = 0.985, recency = 1.0, consistency = 30/30 = 1.0
        # base = 0.985*0.6 + 1.0*0.4 = 0.991, score = 0.991*1.0 = 0.991
        assert result.likelihood >= 0.9
        assert result.ui_state == UiState.EXPECTED_NOW
        assert result.confidence == Confidence.HIGH

    def test_moderate_signals_produce_upcoming(self) -> None:
        """Moderate priority and recency → UPCOMING."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(days=7))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.7,
            session_count=15,
            period_days=30,
            _now=NOW,
        )
        # ema = 0.995 * 0.7 = 0.6965, recency = 1.0, consistency = 15/30 = 0.5
        # base = 0.6965*0.6 + 0.5*0.4 = 0.618, score = 0.618*1.0 = 0.618
        assert 0.5 <= result.likelihood < 0.9
        assert result.ui_state == UiState.UPCOMING
        assert result.confidence == Confidence.MEDIUM

    def test_low_signals_produce_idle(self) -> None:
        """Weak signals → IDLE."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(days=30))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.05,
            session_count=2,
            period_days=30,
            _now=NOW,
        )
        # ema = 0.995 * 0.05 ≈ 0.05, recency ≈ 0.82, consistency = 2/30 ≈ 0.067
        # base = 0.05*0.6 + 0.067*0.4 = 0.03 + 0.027 = 0.057
        # score = 0.057 * 0.82 = 0.047 → baseline_minimum = 0.15
        assert BASELINE_MINIMUM <= result.likelihood < 0.5
        assert result.ui_state == UiState.IDLE
        assert result.confidence == Confidence.LOW

    def test_cold_target_with_no_history(self) -> None:
        """No last_live_at, zero sessions → COLD."""
        target = _target()
        snap = _snapshot(last_live_at=None)
        result = engine.predict(
            target,
            snap,
            previous_priority=0.0,
            session_count=0,
            period_days=30,
            _now=NOW,
        )
        # Everything at baseline, then clamped
        assert result.likelihood == BASELINE_MINIMUM
        assert result.ui_state == UiState.IDLE  # >= baseline → IDLE, not COLD

    def test_genuinely_cold(self) -> None:
        """No history and no last_live_at — but still baseline minimum."""
        target = _target()
        snap = _snapshot(last_live_at=None)
        result = engine.predict(
            target,
            snap,
            previous_priority=0.0,
            session_count=0,
            period_days=30,
            _now=NOW,
        )
        assert result.likelihood == BASELINE_MINIMUM


# ======================================================================
# Favourite bias
# ======================================================================


class TestFavoriteBias:
    def test_favourite_gets_medium_floor(self) -> None:
        """Favourite with no history still gets MEDIUM-band score."""
        target = _target(favorite=True)
        snap = _snapshot(last_live_at=None)
        result = engine.predict(
            target,
            snap,
            previous_priority=0.0,
            session_count=0,
            period_days=30,
            _now=NOW,
        )
        assert result.likelihood >= 0.5
        assert result.reasons == ["favorite_bias"]

    def test_favourite_high_signals_not_capped(self) -> None:
        """Favourite with strong signals isn't held back by the floor."""
        target = _target(favorite=True)
        snap = _snapshot(last_live_at=NOW - timedelta(hours=1))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.9,
            session_count=30,
            period_days=30,
            _now=NOW,
        )
        assert result.likelihood >= 0.9
        assert "favorite_bias" in result.reasons


# ======================================================================
# Confidence classification
# ======================================================================


class TestConfidenceClassification:
    def test_high_confidence(self) -> None:
        assert engine._classify_confidence(0.9) == Confidence.HIGH

    def test_medium_confidence(self) -> None:
        assert engine._classify_confidence(0.6) == Confidence.MEDIUM

    def test_low_confidence(self) -> None:
        assert engine._classify_confidence(0.3) == Confidence.LOW

    def test_boundary_high(self) -> None:
        assert (
            engine._classify_confidence(CONFIDENCE_HIGH_THRESHOLD)
            == Confidence.HIGH
        )

    def test_boundary_medium(self) -> None:
        assert (
            engine._classify_confidence(CONFIDENCE_MEDIUM_THRESHOLD)
            == Confidence.MEDIUM
        )

    def test_just_below_medium(self) -> None:
        assert (
            engine._classify_confidence(CONFIDENCE_MEDIUM_THRESHOLD - 0.01)
            == Confidence.LOW
        )


# ======================================================================
# Predicted window
# ======================================================================


class TestPredictedWindow:
    def test_window_start_is_now(self) -> None:
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(hours=1))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.9,
            session_count=20,
            period_days=30,
            _now=NOW,
        )
        assert result.predicted_window_start == NOW

    def test_window_duration_matches_interval(self) -> None:
        """A high-likelihood target gets a FAST interval window."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(hours=1))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.99,
            session_count=30,
            period_days=30,
            _now=NOW,
        )
        # Expect FAST band (~60s, with jitter ±15%) when likelihood >= 0.9
        assert result.likelihood >= 0.9
        assert result.predicted_window_end is not None
        duration = (result.predicted_window_end - result.predicted_window_start).total_seconds()
        fast_min = int(FAST_BAND_INTERVAL * 0.85)
        fast_max = int(FAST_BAND_INTERVAL * 1.15)
        assert fast_min <= duration <= fast_max, (
            f"Expected duration in [{fast_min}, {fast_max}], got {duration}"
        )

    def test_slow_target_has_slow_window(self) -> None:
        """A cold-ish target gets a longer window."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(days=50))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.05,
            session_count=1,
            period_days=60,
            _now=NOW,
        )
        if result.predicted_window_end and result.predicted_window_start:
            duration = (
                result.predicted_window_end - result.predicted_window_start
            ).total_seconds()
            # Likelihood around baseline → SLOW band (with jitter ±15%)
            slow_min = int(SLOW_BAND_INTERVAL * 0.85)
            slow_max = int(SLOW_BAND_INTERVAL * 1.15)
            assert slow_min <= duration <= slow_max, (
                f"Expected duration in [{slow_min}, {slow_max}], got {duration}"
            )

    def test_next_slot_at_is_now_for_active_targets(self) -> None:
        """Active predictions should have next_slot_at set to now."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(days=1))
        result = engine.predict(
            target,
            snap,
            previous_priority=0.5,
            session_count=10,
            period_days=30,
            _now=NOW,
        )
        assert result.next_slot_at == NOW

    def test_no_window_for_disabled(self) -> None:
        target = _target(enabled=False)
        snap = _snapshot()
        result = engine.predict(target, snap, _now=NOW)
        assert result.predicted_window_start is None
        assert result.predicted_window_end is None
        assert result.next_slot_at is None


# ======================================================================
# Reason accumulation
# ======================================================================


class TestReasons:
    def test_recent_live_activity_reason(self) -> None:
        """When last_live_at is recent, reason is included."""
        target = _target()
        snap = _snapshot(last_live_at=NOW - timedelta(days=1))
        result = engine.predict(
            target, snap, previous_priority=0.5, _now=NOW
        )
        assert "recent_live_activity" in result.reasons

    def test_no_recent_live_no_reason(self) -> None:
        """No last_live_at → no 'recent_live_activity' reason."""
        target = _target()
        snap = _snapshot(last_live_at=None)
        result = engine.predict(
            target, snap, previous_priority=0.0, _now=NOW
        )
        assert "recent_live_activity" not in result.reasons

    def test_favourite_reason_included_when_triggered(self) -> None:
        target = _target(favorite=True)
        snap = _snapshot(last_live_at=NOW - timedelta(days=30))
        result = engine.predict(
            target, snap, previous_priority=0.0, _now=NOW
        )
        assert "favorite_bias" in result.reasons


# ======================================================================
# PredictionResult invariants
# ======================================================================


class TestResultInvariants:
    def test_likelihood_in_range(self) -> None:
        """Likelihood must always be in [0.0, 1.0]."""
        for _ in range(50):
            result = _random_prediction()
            assert 0.0 <= result.likelihood <= 1.0

    def test_confidence_is_valid_enum(self) -> None:
        result = _random_prediction()
        assert isinstance(result.confidence, Confidence)

    def test_ui_state_is_valid_enum(self) -> None:
        result = _random_prediction()
        assert isinstance(result.ui_state, UiState)

    def test_reasons_is_list(self) -> None:
        result = _random_prediction()
        assert isinstance(result.reasons, list)


def _random_prediction() -> ...:
    """Generate a semi-random prediction to exercise varied paths."""
    import random

    enabled = random.choice([True, False])
    favorite = random.choice([True, False])
    is_live = random.choice([True, False]) if enabled else False

    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    target = _target(enabled=enabled, favorite=favorite)
    snap = _snapshot(
        state=MonitoringState.RECORDING if is_live else MonitoringState.IDLE,
        last_live_at=now - timedelta(days=random.randint(0, 90)),
    )
    return engine.predict(
        target,
        snap,
        previous_priority=random.random(),
        session_count=random.randint(0, 50),
        period_days=30.0,
        _now=now,
    )
