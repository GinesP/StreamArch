"""StreamTarget entity — a monitorizable streamer.

Fields:
    id: Unique identifier.
    platform: Platform enum (twitch, tiktok, youtube, …).
    handle: Clean primary handle.
    source_url: Original or canonical URL.
    display_name: Human-readable name for UI.
    enabled: Monitoring active flag.
    favorite: Priority bias flag.
    preferred_quality: Optional quality preference.
    output_profile_id: Optional logical FK to output profile.
    schedule_mode: one of none, hinted, strict_hint.
    created_at, updated_at: Timestamps.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class StreamTarget:
    id: str
    platform: str
    handle: str
    source_url: str
    display_name: str
    enabled: bool
    favorite: bool
    preferred_quality: str | None
    output_profile_id: str | None
    schedule_mode: str  # none | hinted | strict_hint
    created_at: datetime
    updated_at: datetime
