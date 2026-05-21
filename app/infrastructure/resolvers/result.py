"""Result model for stream URL resolution.

``ResolveResult`` is the value object that every resolver returns.
It replaces the earlier ``str | None`` return type and carries enough
metadata for the monitoring system to decide what to do next.
"""

from dataclasses import dataclass


@dataclass
class ResolveResult:
    """The outcome of resolving a stream URL.

    A resolver always returns a ``ResolveResult`` — never ``None``.
    The ``is_live`` flag tells the caller whether a playable stream
    was found, and the URL fields carry the locations.

    Attributes
    ----------
    is_live:
        ``True`` when the stream is currently live and ``stream_url``
        points to a playable media stream.
    stream_url:
        The preferred playable stream URL (maps to streamget's
        ``record_url``).  ``None`` when the stream is not live or
        resolution failed.
    title:
        Stream title as reported by the platform.
    anchor_name:
        Streamer or channel display name.
    m3u8_url:
        Raw HLS playlist URL when the platform provides one separately
        from the "record" URL.
    """

    is_live: bool = False
    stream_url: str | None = None
    title: str | None = None
    anchor_name: str | None = None
    m3u8_url: str | None = None
