"""Basic activation/deactivation rules for stream targets.

These policies operate on the StreamTarget entity to decide
whether monitoring should be enabled, disabled, or force-checked.

No infrastructure dependency — pure domain rules.
"""

from app.domain.stream_target.entities import StreamTarget


def can_enable(target: StreamTarget) -> bool:
    """Return True if the target is eligible for monitoring."""
    return not target.enabled and bool(target.handle)


def can_disable(target: StreamTarget) -> bool:
    """Return True if the target can be disabled safely."""
    return target.enabled
