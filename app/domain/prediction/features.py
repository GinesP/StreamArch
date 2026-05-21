"""Prediction features — independent signal calculations.

Each function computes one aspect of the likelihood estimate.
The engine combines these signals into a unified PredictionResult.

All constants are the proven default values from StreamCapOrigin.
"""

from dataclasses import dataclass
from datetime import datetime

# ── EMA defaults ────────────────────────────────────────────────────

EMA_ALPHA_LIVE: float = 0.1
"""Adaptation rate when the target is live — climbs quickly toward 1.0."""

EMA_ALPHA_OFFLINE: float = 0.005
"""Decay rate when the target is offline — fades very slowly."""

# ── Recency defaults ────────────────────────────────────────────────

RECENCY_DAYS_THRESHOLD_1: int = 14
"""First recency cliff — beyond this many days the factor drops."""

RECENCY_DAYS_THRESHOLD_2: int = 45
"""Second recency cliff — beyond this many days the factor drops further."""

RECENCY_DAYS_MAX: int = 60
"""Days after which linear decay toward baseline_minimum begins."""

RECENCY_DECAY_14D: float = 0.82
"""Recency multiplier after 14 days."""

RECENCY_DECAY_45D: float = 0.70
"""Recency multiplier after 45 days."""

# ── Likelihood defaults ─────────────────────────────────────────────

BASELINE_MINIMUM: float = 0.15
"""Floor for any likelihood score, even with zero data."""

LIKELIHOOD_MEDIUM_THRESHOLD: float = 0.5
"""Favourites never drop below this threshold."""


@dataclass
class PredictionFeatures:
    """Aggregated signals that feed into the unified likelihood.

    Each field is a *computed* value — the engine never sees raw input.
    This structure is useful for debugging, auditing, and serialisation
    of intermediate results.
    """

    hourly_pattern_score: float
    session_pattern_score: float
    schedule_hint_score: float
    recency_factor: float
    consistency_factor: float
    ema_priority: float
    favorite_bias: float
    computed_at: datetime


# ── Signal calculations ─────────────────────────────────────────────


def calculate_ema(
    current_priority: float,
    is_live: bool,
    is_recording: bool,
    *,
    alpha_live: float = EMA_ALPHA_LIVE,
    alpha_offline: float = EMA_ALPHA_OFFLINE,
) -> float:
    """Update an exponential moving average of streaming priority.

    When the target is *live* (or being recorded) the EMA climbs toward
    1.0 at *alpha_live* rate.  When offline it decays toward 0.0 at the
    much slower *alpha_offline* rate.

    This prevents brief outages from collapsing the score and prevents
    single live events from inflating it permanently.
    """
    if is_live or is_recording:
        return alpha_live * 1.0 + (1.0 - alpha_live) * current_priority
    return (1.0 - alpha_offline) * current_priority


def calculate_recency_factor(
    last_live_at: datetime | None,
    now: datetime,
    *,
    threshold_1: int = RECENCY_DAYS_THRESHOLD_1,
    threshold_2: int = RECENCY_DAYS_THRESHOLD_2,
    days_max: int = RECENCY_DAYS_MAX,
    decay_14d: float = RECENCY_DECAY_14D,
    decay_45d: float = RECENCY_DECAY_45D,
    baseline: float = BASELINE_MINIMUM,
) -> float:
    """Return a multiplier in [*baseline*, 1.0] based on how recently the
    target was last seen live.

    Steps
        *last_live_at* is ``None`` → *baseline*
        ≤ *threshold_1* days      → 1.0 (fresh)
        ≤ *threshold_2* days      → *decay_14d*
        ≤ *days_max* days         → *decay_45d*
        > *days_max* days         → linear decay from *decay_45d* to *baseline*

    When there is no prior live event the function returns the baseline
    minimum — we simply do not know.
    """
    if last_live_at is None:
        return baseline

    days_since = (now - last_live_at).days
    if days_since < 0:
        # Clock skew — treat as fresh
        return 1.0

    if days_since <= threshold_1:
        return 1.0
    if days_since <= threshold_2:
        return decay_14d
    if days_since <= days_max:
        return decay_45d

    # Linear decay from decay_45d down to baseline over the same span
    # as days_max (so at 2 × days_max we reach baseline).
    extra_days = days_since - days_max
    slope = (decay_45d - baseline) / days_max
    return max(baseline, decay_45d - slope * extra_days)


def calculate_consistency(
    session_count: int,
    period_days: float,
) -> float:
    """Score how consistently the target streams.

    Defined as the *session density* — the ratio of observed sessions
    to the observation period in days, capped at 1.0.

    A streamer who goes live every day (30 sessions in 30 days) scores
    1.0.  Someone who streams twice a week (≈8 sessions in 30 days)
    scores ≈0.27.
    """
    if period_days <= 0 or session_count <= 0:
        return 0.0
    density = session_count / period_days
    return min(1.0, density)


def calculate_likelihood(
    ema: float,
    recency: float,
    consistency: float,
    favorite: bool,
    *,
    ema_weight: float = 0.6,
    consistency_weight: float = 0.4,
    baseline: float = BASELINE_MINIMUM,
    favorite_floor: float = LIKELIHOOD_MEDIUM_THRESHOLD,
) -> float:
    """Combine signals into a unified likelihood score in [0.0, 1.0].

    The formula is a weighted average of *ema* and *consistency*,
    multiplied by *recency* (which acts as a decay factor), then
    clamped to [*baseline*, 1.0].

    When *favorite* is ``True`` the score never drops below
    *favorite_floor* (which means a favourite always gets at least
    a MEDIUM queue band).
    """
    base = min(1.0, ema * ema_weight + consistency * consistency_weight)
    score = base * recency
    score = max(score, baseline)
    if favorite:
        score = max(score, favorite_floor)
    return min(1.0, score)
