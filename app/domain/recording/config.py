"""RecordingConfig — per-stream or global recording behavior configuration.

Hierarchy (future)
------------------
Stream override → global config → internal defaults

For now the resolution layer only knows about internal defaults and global
configuration.  Stream-level overrides will be added here when per-stream
recording fields are introduced on ``StreamTarget``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecordingConfig:
    """Resolved recording behavior for a stream.

    Parameters
    ----------
    segment_enabled:
        If ``True`` the recording is split into segments of
        *segment_time_seconds* each.  Default ``False``.
    segment_time_seconds:
        Target segment duration (seconds) when *segment_enabled* is
        ``True``.  Default 3600 (1 hour).
    per_stream_directory:
        If ``True`` the recording file is placed in a sub-directory
        named after the stream's handle.  Default ``False`` (flat
        recordings directory).
    convert_to_mp4:
        If ``True`` the temporary ``.ts`` file is transmuxed to
        ``.mp4`` after the recording stops.  Default ``True``.
    """

    segment_enabled: bool = False
    segment_time_seconds: int = 1800
    per_stream_directory: bool = False
    convert_to_mp4: bool = True


def resolve_recording_config(
    global_config: RecordingConfig | None = None,
) -> RecordingConfig:
    """Resolve the effective recording config for a stream.

    For now this returns the global config (or internal defaults).
    The stream-override layer will be inserted here when per-stream
    configuration fields are introduced on ``StreamTarget``.

    Parameters
    ----------
    global_config:
        The global recording config from ``AppConfig``.  ``None`` will
        fall back to internal defaults.

    Returns
    -------
    A fully-populated ``RecordingConfig``.
    """
    if global_config is not None:
        return RecordingConfig(
            segment_enabled=global_config.segment_enabled,
            segment_time_seconds=global_config.segment_time_seconds,
            per_stream_directory=global_config.per_stream_directory,
            convert_to_mp4=global_config.convert_to_mp4,
        )
    return RecordingConfig()
