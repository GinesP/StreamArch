"""Scheduling policy — maps likelihood scores to intervals and queue bands.

This is pure domain logic: given a likelihood score and whether the
target is a favourite, decide how urgently the scheduler should check it
and which queue it belongs in.
"""

import random

from app.domain.shared.types import QueueBand

# ── Interval defaults (seconds) ─────────────────────────────────────

FAST_BAND_INTERVAL: int = 60
"""Check every ~60 seconds when likelihood is very high."""

MEDIUM_BAND_INTERVAL: int = 300
"""Check every ~5 minutes when likelihood is moderate."""

SLOW_BAND_INTERVAL: int = 900
"""Check every ~15 minutes for low-likelihood targets."""

DEEP_SLEEP_INTERVAL: int = 2700
"""Check every ~45 minutes for targets with very low likelihood AND
low priority score (historically inactive).  Avoids burning resources
on streams that never go live."""

# ── Likelihood thresholds ───────────────────────────────────────────

LIKELIHOOD_FAST_THRESHOLD: float = 0.9
"""Likelihood at or above this → FAST queue band."""

LIKELIHOOD_MEDIUM_THRESHOLD: float = 0.5
"""Likelihood at or above this → MEDIUM queue band."""

LIKELIHOOD_SLOW_THRESHOLD: float = 0.15
"""Likelihood at or below this → SLOW queue band."""

# ── Deep sleep thresholds ───────────────────────────────────────────

DEEP_SLEEP_PRIORITY_THRESHOLD: float = 0.01
"""Priority score must be below this to enter deep sleep."""

DEEP_SLEEP_CHECK_THRESHOLD: int = 30
"""Minimum number of live checks before deep sleep is considered."""

# ── New-stream promotion ──────────────────────────────────────────────

NEW_STREAM_PROMOTION_CHECKS: int = 3
"""Number of initial checks during which a stream with no history is
promoted to MEDIUM interval instead of SLOW."""

NEW_STREAM_PROMOTION_INTERVAL: int = 300
"""Interval (seconds) for promoted new streams (same as MEDIUM)."""

# ── Jitter ──────────────────────────────────────────────────────────

JITTER_PCT: float = 0.15
"""Default jitter range: ±15 %."""

# ── Favourite floor ─────────────────────────────────────────────────

FAVORITE_MIN_BAND: QueueBand = QueueBand.MEDIUM
"""Favourites are never demoted below MEDIUM."""

# ── Favourite max interval ──────────────────────────────────────────

FAVORITE_MAX_INTERVAL: int = 180
"""Favourites never exceed this check interval (3 minutes), even when
the likelihood score is low."""


def get_interval_seconds(
    likelihood: float,
    is_favorite: bool = False,
    *,
    fast_interval: int = FAST_BAND_INTERVAL,
    medium_interval: int = MEDIUM_BAND_INTERVAL,
    slow_interval: int = SLOW_BAND_INTERVAL,
    fast_threshold: float = LIKELIHOOD_FAST_THRESHOLD,
    medium_threshold: float = LIKELIHOOD_MEDIUM_THRESHOLD,
) -> int:
    """Return the base check interval for a given likelihood.

    Favourites are boosted to at least the MEDIUM interval, so even a
    low-likelihood favourite gets checked every *medium_interval*
    seconds.
    """
    effective = likelihood
    if is_favorite:
        effective = max(effective, medium_threshold)

    if effective >= fast_threshold:
        return fast_interval
    if effective >= medium_threshold:
        return medium_interval
    return slow_interval


def get_adjusted_interval(
    likelihood: float,
    priority_score: float,
    is_favorite: bool,
    live_check_count: int = 0,
    *,
    fast_interval: int = FAST_BAND_INTERVAL,
    medium_interval: int = MEDIUM_BAND_INTERVAL,
    slow_interval: int = SLOW_BAND_INTERVAL,
    deep_sleep_interval: int = DEEP_SLEEP_INTERVAL,
    fast_threshold: float = LIKELIHOOD_FAST_THRESHOLD,
    medium_threshold: float = LIKELIHOOD_MEDIUM_THRESHOLD,
    deep_sleep_priority_threshold: float = DEEP_SLEEP_PRIORITY_THRESHOLD,
    deep_sleep_check_threshold: int = DEEP_SLEEP_CHECK_THRESHOLD,
    favorite_max_interval: int = FAVORITE_MAX_INTERVAL,
    new_stream_promotion_checks: int = NEW_STREAM_PROMOTION_CHECKS,
    new_stream_promotion_interval: int = NEW_STREAM_PROMOTION_INTERVAL,
) -> int:
    """Return the adapted check interval for a given likelihood and
    historical priority.

    This matches StreamCap's ``get_adjusted_interval()`` behaviour:
    * Likelihood ≥ 0.9     → FAST (~60s)
    * Likelihood ≥ 0.5     → MEDIUM (~300s)
    * **New stream**        → MEDIUM (~300s) — for the first N checks,
      a newly added target is promoted so it gets reasonable attention
      before the predictor has enough data to judge it.
    * Deep sleep           → DEEP (~2700s, 45 min) — only when
      priority_score is VERY low AND the stream has been checked
      enough times for the predictor to be confident.
    * Likelihood ≤ 0.15    → SLOW (~900s)
    * Otherwise            → SLOW (~900s)

    Favourites never exceed *favorite_max_interval* (3 min).
    Jitter (±15 %) is applied on top of the base interval.
    """
    effective = likelihood
    if is_favorite:
        effective = max(effective, medium_threshold)

    # Determine base interval
    if effective >= fast_threshold:
        base = fast_interval
    elif effective >= medium_threshold:
        base = medium_interval
    elif (live_check_count < new_stream_promotion_checks
          and priority_score < medium_threshold):
        # New stream promotion: give MEDIUM attention for the first
        # few checks until the predictor gathers enough data.
        base = new_stream_promotion_interval
    elif (priority_score < deep_sleep_priority_threshold
          and live_check_count >= deep_sleep_check_threshold):
        base = deep_sleep_interval
    elif effective <= 0.15:
        base = slow_interval
    else:
        base = slow_interval

    # Favourites cap
    if is_favorite and base > favorite_max_interval:
        base = favorite_max_interval

    return apply_jitter(base)


def get_queue_band(
    likelihood: float,
    is_favorite: bool = False,
    *,
    fast_threshold: float = LIKELIHOOD_FAST_THRESHOLD,
    medium_threshold: float = LIKELIHOOD_MEDIUM_THRESHOLD,
) -> QueueBand:
    """Map a likelihood score to a ``QueueBand``.

    The mapping mirrors ``get_interval_seconds``:
        ≥ *fast_threshold*  → FAST
        ≥ *medium_threshold* → MEDIUM
        else                → SLOW

    Favourites are raised to at least MEDIUM.
    """
    effective = likelihood
    if is_favorite:
        effective = max(effective, medium_threshold)

    if effective >= fast_threshold:
        return QueueBand.FAST
    if effective >= medium_threshold:
        return QueueBand.MEDIUM
    return QueueBand.SLOW


def apply_jitter(
    interval_seconds: int,
    jitter_pct: float = JITTER_PCT,
) -> int:
    """Add random jitter within ±*jitter_pct* of the base interval.

    Jitter prevents the scheduler from producing clockwork-check patterns
    that streaming platforms could detect as bot traffic.
    """
    delta = max(1, int(interval_seconds * jitter_pct))
    return interval_seconds + random.randint(-delta, delta)
