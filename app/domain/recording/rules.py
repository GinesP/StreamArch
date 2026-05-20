"""Domain rules for recording session lifecycle.

Decides when a session should close, split, or trigger remux.
"""

from app.domain.shared.types import ContainerFormat, RecordingStatus


def requires_remux(container_format: ContainerFormat) -> bool:
    """Return True if the format should be remuxed to mp4."""
    return container_format in (ContainerFormat.TS, ContainerFormat.MKV)


def can_close_session(status: RecordingStatus) -> bool:
    """Return True if the session can be closed (marked as completed).

    Only sessions that are currently recording can transition to completed.
    """
    return status == RecordingStatus.RECORDING
