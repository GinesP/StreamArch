"""Tests for prediction feature calculations.

Every signal function is tested in isolation:
    - calculate_ema
    - calculate_recency_factor
    - calculate_consistency
    - calculate_likelihood
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.prediction.features import (
    BASELINE_MINIMUM,
    LIKELIHOOD_MEDIUM_THRESHOLD,
    calculate_consistency,
    calculate_ema,
    calculate_likelihood,
    calculate_recency_factor,
)


# ======================================================================
# calculate_ema
# ======================================================================


class TestCalculateEma:
    def test_live_pulls_toward_one(self) -> None:
        """When live, EMA climbs toward 1.0 at alpha_live rate."""
        result = calculate_ema(0.0, is_live=True, is_recording=False)
        assert result == pytest.approx(0.1)  # 0.1 * 1.0 + 0.9 * 0.0

    def test_recording_pulls_toward_one(self) -> None:
        """Recording counts as live for EMA purposes."""
        result = calculate_ema(0.0, is_live=False, is_recording=True)
        assert result == pytest.approx(0.1)

    def test_offline_decays_slowly(self) -> None:
        """When offline, EMA decays toward 0.0 at alpha_offline rate."""
        result = calculate_ema(1.0, is_live=False, is_recording=False)
        assert result == pytest.approx(0.995)  # 0.995 * 1.0

    def test_persistent_live_converges_to_one(self) -> None:
        """Repeated live updates should approach 1.0."""
        prio = 0.0
        for _ in range(100):
            prio = calculate_ema(prio, is_live=True, is_recording=False)
        assert prio == pytest.approx(1.0, abs=1e-4)

    def test_persistent_offline_converges_to_zero(self) -> None:
        """Repeated offline updates should approach 0.0."""
        prio = 1.0
        for _ in range(2000):
            prio = calculate_ema(prio, is_live=False, is_recording=False)
        assert prio == pytest.approx(0.0, abs=1e-4)

    def test_custom_alpha(self) -> None:
        """Custom alpha values should be respected."""
        result = calculate_ema(0.5, is_live=True, is_recording=False, alpha_live=0.5)
        assert result == pytest.approx(0.75)  # 0.5 * 1.0 + 0.5 * 0.5

    def test_custom_alpha_offline(self) -> None:
        result = calculate_ema(0.5, is_live=False, is_recording=False, alpha_offline=0.1)
        assert result == pytest.approx(0.45)  # 0.9 * 0.5

    def test_stays_in_bounds(self) -> None:
        """EMA should never exceed [0, 1]."""
        prio = 0.0
        for _ in range(50):
            prio = calculate_ema(prio, is_live=True, is_recording=False)
        assert 0.0 <= prio <= 1.0

        prio = 1.0
        for _ in range(2000):
            prio = calculate_ema(prio, is_live=False, is_recording=False)
        assert 0.0 <= prio <= 1.0


# ======================================================================
# calculate_recency_factor
# ======================================================================


class TestCalculateRecencyFactor:
    NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)

    def test_no_history_returns_baseline(self) -> None:
        assert calculate_recency_factor(None, self.NOW) == BASELINE_MINIMUM

    def test_just_now_returns_one(self) -> None:
        last = self.NOW - timedelta(hours=1)
        assert calculate_recency_factor(last, self.NOW) == 1.0

    def test_exactly_14_days_returns_one(self) -> None:
        last = self.NOW - timedelta(days=14)
        assert calculate_recency_factor(last, self.NOW) == 1.0

    def test_15_days_returns_decay_14d(self) -> None:
        last = self.NOW - timedelta(days=15)
        assert calculate_recency_factor(last, self.NOW) == pytest.approx(0.82)

    def test_exactly_45_days_returns_decay_14d(self) -> None:
        last = self.NOW - timedelta(days=45)
        assert calculate_recency_factor(last, self.NOW) == pytest.approx(0.82)

    def test_46_days_returns_decay_45d(self) -> None:
        last = self.NOW - timedelta(days=46)
        assert calculate_recency_factor(last, self.NOW) == pytest.approx(0.70)

    def test_exactly_60_days_returns_decay_45d(self) -> None:
        last = self.NOW - timedelta(days=60)
        assert calculate_recency_factor(last, self.NOW) == pytest.approx(0.70)

    def test_beyond_max_decays_linearly(self) -> None:
        """At 90 days (60 + 30), factor should be halfway between 0.70
        and baseline_minimum (0.15)."""
        last = self.NOW - timedelta(days=90)
        result = calculate_recency_factor(last, self.NOW)
        # linear: 0.70 - (0.70-0.15) * 30/60 = 0.70 - 0.275 = 0.425
        assert result == pytest.approx(0.425, abs=0.01)

    def test_very_old_converges_to_baseline(self) -> None:
        last = self.NOW - timedelta(days=365)
        assert calculate_recency_factor(last, self.NOW) == pytest.approx(
            BASELINE_MINIMUM, abs=0.01
        )

    def test_clock_skew_returns_one(self) -> None:
        """When last_live_at is in the future, treat as fresh."""
        last = self.NOW + timedelta(hours=1)
        assert calculate_recency_factor(last, self.NOW) == 1.0


# ======================================================================
# calculate_consistency
# ======================================================================


class TestCalculateConsistency:
    def test_zero_sessions_returns_zero(self) -> None:
        assert calculate_consistency(0, 30.0) == 0.0

    def test_zero_period_returns_zero(self) -> None:
        assert calculate_consistency(5, 0.0) == 0.0

    def test_negative_period_returns_zero(self) -> None:
        assert calculate_consistency(5, -10.0) == 0.0

    def test_daily_streamer_scores_one(self) -> None:
        """30 sessions in 30 days → density = 1.0."""
        assert calculate_consistency(30, 30.0) == 1.0

    def test_weekly_streamer_scores_proportionally(self) -> None:
        """~4 sessions in 30 days → density ≈ 0.13."""
        result = calculate_consistency(4, 30.0)
        assert result == pytest.approx(0.1333, abs=0.01)

    def test_density_capped_at_one(self) -> None:
        """More than 1 session per day is still 1.0."""
        assert calculate_consistency(100, 30.0) == 1.0

    def test_single_session_single_day(self) -> None:
        assert calculate_consistency(1, 1.0) == 1.0

    def test_integer_days(self) -> None:
        assert calculate_consistency(5, 10) == 0.5


# ======================================================================
# calculate_likelihood
# ======================================================================


class TestCalculateLikelihood:
    def test_high_signals_produce_high_likelihood(self) -> None:
        """All signals strong → near 1.0."""
        result = calculate_likelihood(ema=0.9, recency=1.0, consistency=0.9, favorite=False)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_low_signals_produce_baseline(self) -> None:
        """All signals weak → baseline minimum."""
        result = calculate_likelihood(ema=0.0, recency=0.0, consistency=0.0, favorite=False)
        assert result == BASELINE_MINIMUM

    def test_recency_decays_score(self) -> None:
        """Low recency should drag the weighted average down."""
        high_base = calculate_likelihood(ema=0.9, recency=1.0, consistency=0.9, favorite=False)
        decayed = calculate_likelihood(ema=0.9, recency=0.5, consistency=0.9, favorite=False)
        assert decayed < high_base

    def test_favorite_floor_applied(self) -> None:
        """Even with zero signals, a favourite gets MEDIUM threshold."""
        result = calculate_likelihood(ema=0.0, recency=0.0, consistency=0.0, favorite=True)
        assert result >= LIKELIHOOD_MEDIUM_THRESHOLD

    def test_favorite_still_allows_high_score(self) -> None:
        """Favourite floor does not cap a naturally high score."""
        result = calculate_likelihood(ema=0.9, recency=1.0, consistency=0.9, favorite=True)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_result_clamped_to_one(self) -> None:
        """Combined score never exceeds 1.0."""
        result = calculate_likelihood(ema=1.0, recency=1.0, consistency=1.0, favorite=True)
        assert result == 1.0

    def test_ema_weighted_over_consistency(self) -> None:
        """EMA dominates because of 0.6 vs 0.4 weights."""
        low_ema = calculate_likelihood(ema=0.2, recency=1.0, consistency=0.9, favorite=False)
        low_cons = calculate_likelihood(ema=0.9, recency=1.0, consistency=0.2, favorite=False)
        # EMA 0.2 + consistency 0.9 → base = 0.12 + 0.36 = 0.48
        # EMA 0.9 + consistency 0.2 → base = 0.54 + 0.08 = 0.62
        assert low_cons > low_ema

    def test_zero_ema_high_consistency(self) -> None:
        """Brand new streamer with good history elsewhere."""
        # base = 0.0*0.6 + 0.8*0.4 = 0.32, score = 0.32*1.0 = 0.32
        result = calculate_likelihood(ema=0.0, recency=1.0, consistency=0.8, favorite=False)
        assert result == pytest.approx(0.32)
