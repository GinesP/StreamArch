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

# ── Likelihood thresholds ───────────────────────────────────────────

LIKELIHOOD_FAST_THRESHOLD: float = 0.9
"""Likelihood at or above this → FAST queue band."""

LIKELIHOOD_MEDIUM_THRESHOLD: float = 0.5
"""Likelihood at or above this → MEDIUM queue band."""

LIKELIHOOD_SLOW_THRESHOLD: float = 0.15
"""Likelihood at or below this → SLOW queue band."""

# ── Jitter ──────────────────────────────────────────────────────────

JITTER_PCT: float = 0.15
"""Default jitter range: ±15 %."""

# ── Favourite floor ─────────────────────────────────────────────────

FAVORITE_MIN_BAND: QueueBand = QueueBand.MEDIUM
"""Favourites are never demoted below MEDIUM."""


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
