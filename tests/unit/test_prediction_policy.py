"""Tests for scheduling policy — interval, queue band, and jitter."""

import pytest

from app.domain.prediction.policy import (
    FAST_BAND_INTERVAL,
    MEDIUM_BAND_INTERVAL,
    SLOW_BAND_INTERVAL,
    LIKELIHOOD_FAST_THRESHOLD,
    LIKELIHOOD_MEDIUM_THRESHOLD,
    apply_jitter,
    get_interval_seconds,
    get_queue_band,
)
from app.domain.shared.types import QueueBand


# ======================================================================
# get_interval_seconds
# ======================================================================


class TestGetIntervalSeconds:
    def test_fast_band_at_threshold(self) -> None:
        assert get_interval_seconds(LIKELIHOOD_FAST_THRESHOLD) == FAST_BAND_INTERVAL

    def test_fast_band_above_threshold(self) -> None:
        assert get_interval_seconds(0.95) == FAST_BAND_INTERVAL

    def test_medium_band_at_threshold(self) -> None:
        assert get_interval_seconds(LIKELIHOOD_MEDIUM_THRESHOLD) == MEDIUM_BAND_INTERVAL

    def test_medium_band_below_fast(self) -> None:
        assert get_interval_seconds(0.7) == MEDIUM_BAND_INTERVAL

    def test_slow_band_below_medium(self) -> None:
        assert get_interval_seconds(0.3) == SLOW_BAND_INTERVAL

    def test_slow_band_at_zero(self) -> None:
        assert get_interval_seconds(0.0) == SLOW_BAND_INTERVAL

    def test_favourite_boosted_to_medium(self) -> None:
        """Favourite with low likelihood still gets MEDIUM interval."""
        assert get_interval_seconds(0.1, is_favorite=True) == MEDIUM_BAND_INTERVAL

    def test_favourite_not_boosted_past_own_score(self) -> None:
        """Favourite with already-high score stays fast."""
        assert get_interval_seconds(0.95, is_favorite=True) == FAST_BAND_INTERVAL

    def test_custom_parameters(self) -> None:
        assert get_interval_seconds(
            0.8, fast_threshold=0.8, medium_threshold=0.3
        ) == FAST_BAND_INTERVAL


# ======================================================================
# get_queue_band
# ======================================================================


class TestGetQueueBand:
    def test_fast_band_at_threshold(self) -> None:
        assert get_queue_band(LIKELIHOOD_FAST_THRESHOLD) == QueueBand.FAST

    def test_fast_band_above(self) -> None:
        assert get_queue_band(1.0) == QueueBand.FAST

    def test_medium_band(self) -> None:
        assert get_queue_band(0.7) == QueueBand.MEDIUM

    def test_slow_band(self) -> None:
        assert get_queue_band(0.1) == QueueBand.SLOW

    def test_favourite_never_below_medium(self) -> None:
        assert get_queue_band(0.0, is_favorite=True) == QueueBand.MEDIUM

    def test_favourite_allows_fast(self) -> None:
        assert get_queue_band(0.95, is_favorite=True) == QueueBand.FAST


# ======================================================================
# apply_jitter
# ======================================================================


class TestApplyJitter:
    def test_jitter_within_range(self) -> None:
        """Result should be within ±15 % of base."""
        base = 300
        for _ in range(100):
            result = apply_jitter(base, jitter_pct=0.15)
            assert 255 <= result <= 345

    def test_deterministic_seed(self) -> None:
        """With a fixed seed, jitter produces reproducible results."""
        import random

        random.seed(42)
        a = apply_jitter(300)
        random.seed(42)
        b = apply_jitter(300)
        assert a == b

    def test_custom_jitter_pct(self) -> None:
        base = 1000
        for _ in range(100):
            result = apply_jitter(base, jitter_pct=0.05)
            assert 950 <= result <= 1050

    def test_zero_jitter_returns_base(self) -> None:
        assert apply_jitter(300, jitter_pct=0.0) == 300

    def test_short_interval_stays_positive(self) -> None:
        """Even with large jitter, interval should not go negative."""
        for _ in range(100):
            assert apply_jitter(10, jitter_pct=0.5) >= 1
