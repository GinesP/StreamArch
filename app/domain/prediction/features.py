"""Prediction features — independent signal calculations.

Each function computes one aspect of the likelihood estimate.
The engine combines these signals into a unified PredictionResult.

All constants are the proven default values from StreamCapOrigin.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

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

# ── Session window defaults ─────────────────────────────────────────

SESSION_MAX_AGE_DAYS: int = 90
"""Sessions older than this are ignored."""

SESSION_PROXIMITY_MINUTES: int = 240
"""Window of influence for session-based pattern (4 hours)."""

SESSION_HOURLY_INFLUENCE_HOURS: float = 3.0
"""How far (in hours) a known live hour influences the score."""

SESSION_CLUSTER_MAX_GAP_HOURS: int = 4
"""Max gap between hours to consider them the same cluster."""


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


def calculate_hourly_pattern(
    sessions: list,
    now: datetime,
    *,
    max_age_days: int = SESSION_MAX_AGE_DAYS,
    influence_hours: float = SESSION_HOURLY_INFLUENCE_HOURS,
    cluster_max_gap: int = SESSION_CLUSTER_MAX_GAP_HOURS,
    baseline: float = BASELINE_MINIMUM,
) -> float:
    """Score how close the current hour is to the streamer's known
    live hours, based on completed recording sessions.

    Returns a score in [*baseline*, ~0.80] — high when the current
    hour falls within a cluster of historically active hours.
    """
    current_hour = now.hour

    # Collect active hours from recent sessions
    active_hours: set[int] = set()
    for s in sessions:
        if s.started_at and (now - s.started_at).days <= max_age_days:
            active_hours.add(s.started_at.hour)

    if not active_hours:
        return 0.0

    # Cluster hours where consecutive gap ≤ cluster_max_gap
    sorted_hours = sorted(active_hours)
    clusters: list[list[int]] = []
    current_cluster = [sorted_hours[0]]
    for h in sorted_hours[1:]:
        if h - current_cluster[-1] <= cluster_max_gap:
            current_cluster.append(h)
        else:
            clusters.append(current_cluster)
            current_cluster = [h]
    clusters.append(current_cluster)

    # Find the closest hour in any cluster
    nearest_dist = min(abs(current_hour - h) for h in active_hours)

    # Score based on proximity (within influence window)
    max_influence_minutes = influence_hours * 60.0
    proximity = max(0.0, 1.0 - (nearest_dist * 60.0 / max_influence_minutes))
    return max(baseline, 0.25 + proximity * 0.55)


def calculate_session_pattern(
    sessions: list,
    now: datetime,
    *,
    max_age_days: int = SESSION_MAX_AGE_DAYS,
    proximity_minutes: int = SESSION_PROXIMITY_MINUTES,
    baseline: float = BASELINE_MINIMUM,
) -> float:
    """Score based on detailed session analysis — the closest session
    to the current time-of-day and day-of-week.

    Returns a score in [*baseline*, 0.85] — high when there is a known
    session starting close to now on this day of the week.
    """
    current_weekday = now.weekday()
    current_minutes = now.hour * 60 + now.minute

    weighted_hits = 0.0
    weighted_total = 0.0

    for s in sessions:
        if not s.started_at:
            continue
        age_days = (now - s.started_at).days
        if age_days < 0 or age_days > max_age_days:
            continue

        # Weight decays with age
        weight = 1.0 / (1.0 + age_days / 21.0)

        # Bonus for matching day of week
        session_weekday = s.started_at.weekday()
        day_weight = weight * (1.25 if session_weekday == current_weekday else 0.35)

        # Proximity: how close is this session's start to current time?
        session_minutes = s.started_at.hour * 60 + s.started_at.minute
        dist = abs(current_minutes - session_minutes)
        proximity = max(0.0, 1.0 - (dist / proximity_minutes))

        weighted_hits += day_weight * proximity
        weighted_total += day_weight

    if weighted_total <= 0:
        return baseline

    session_score = weighted_hits / weighted_total
    return baseline + session_score * (0.85 - baseline)


def calculate_likelihood(
    ema: float,
    recency: float,
    consistency: float,
    favorite: bool,
    *,
    hourly_pattern: float = 0.0,
    session_pattern: float = 0.0,
    baseline: float = BASELINE_MINIMUM,
    favorite_floor: float = LIKELIHOOD_MEDIUM_THRESHOLD,
) -> float:
    """Combine signals into a unified likelihood score in [0.0, 1.0].

    *ema* and *consistency* are the core signals (weighted average).
    *hourly_pattern* and *session_pattern* add a bonus on top when
    historical session data is available, but never reduce the core
    score.

    The combined score is multiplied by *recency* (decay factor), then
    clamped to [*baseline*, 1.0].

    When *favorite* is ``True`` the score never drops below
    *favorite_floor*.
    """
    # Core: EMA + consistency (same weights as before Fase 4)
    core = ema * 0.6 + consistency * 0.4
    # Bonus: session-based signals (only when data exists)
    bonus = max(0.0, hourly_pattern) * 0.10 + max(0.0, session_pattern) * 0.05
    base = min(1.0, core + bonus)
    score = base * recency
    score = max(score, baseline)
    if favorite:
        score = max(score, favorite_floor)
    return min(1.0, score)
