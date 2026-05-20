"""Allowed state transitions for the monitoring state machine.

Each function validates whether a transition is permitted
given the current state — no infrastructure needed.
"""

from .states import MonitoringState


# Map of (current_state, target_state) -> allowed
_ALLOWED_TRANSITIONS: set[tuple[MonitoringState, MonitoringState]] = {
    (MonitoringState.IDLE, MonitoringState.CHECKING),
    (MonitoringState.CHECKING, MonitoringState.RECORDING),
    (MonitoringState.CHECKING, MonitoringState.IDLE),
    (MonitoringState.RECORDING, MonitoringState.POST_PROCESSING),
    (MonitoringState.RECORDING, MonitoringState.ERROR),
    (MonitoringState.POST_PROCESSING, MonitoringState.IDLE),
    (MonitoringState.POST_PROCESSING, MonitoringState.ERROR),
    (MonitoringState.ERROR, MonitoringState.IDLE),
    (MonitoringState.ERROR, MonitoringState.CHECKING),
}


def can_transition(current: MonitoringState, target: MonitoringState) -> bool:
    """Check if a state transition is allowed by domain rules."""
    return (current, target) in _ALLOWED_TRANSITIONS
