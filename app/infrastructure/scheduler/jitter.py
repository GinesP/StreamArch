"""Jitter — adds randomness to check intervals to avoid detectable patterns.

Default jitter range: ±15% of the base interval.
"""

import random


def apply_jitter(interval_seconds: int, jitter_pct: float = 0.15) -> int:
    """Apply random jitter to an interval.

    Args:
        interval_seconds: Base interval.
        jitter_pct: Fraction of interval to jitter (default 0.15 = ±15%).

    Returns:
        Jittered interval in seconds.
    """
    delta = int(interval_seconds * jitter_pct)
    return interval_seconds + random.randint(-delta, delta)
