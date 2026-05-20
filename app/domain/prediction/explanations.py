"""Explainable reasons for prediction decisions.

Each reason is a short, structured string used in the PredictionResult.
Consumers (UI, logs) can use these for debugging and display.
"""


def strong_session_pattern() -> str:
    return "strong_session_pattern"


def recent_live_activity() -> str:
    return "recent_live_activity"


def favorite_bias() -> str:
    return "favorite_bias"


def schedule_hint_active() -> str:
    return "schedule_hint_active"


def hourly_pattern_peak() -> str:
    return "hourly_pattern_peak"


def low_confidence_no_data() -> str:
    return "low_confidence_no_data"


def disabled_target() -> str:
    return "disabled_target"
