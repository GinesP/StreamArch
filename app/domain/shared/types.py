"""Common types shared across domain modules.

Includes result wrappers, shared enums, and clock abstractions.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")

# ── Result type ──────────────────────────────────────────────────────


@dataclass
class Ok(Generic[T]):
    value: T


@dataclass
class Err(Generic[E]):
    error: E


Result = Ok[T] | Err[E]


# ── Policy: Timezone-aware UTC ───────────────────────────────────────
#
# Every datetime in the system MUST be timezone-aware and represent UTC.
# Naive datetimes breed ambiguity — use `utc_now()` instead of
# `datetime.utcnow()` (deprecated) or `datetime.now()` (local time).
#
# Persisted datetimes round-trip through `.isoformat()` →
# `datetime.fromisoformat()`, which preserves the ``+00:00`` suffix.
# ─────────────────────────────────────────────────────────────────────


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ── Domain clock ─────────────────────────────────────────────────────


class DomainClock:
    """Abstract clock so domain logic stays testable."""

    def now(self) -> datetime:
        return utc_now()


# ── Shared enums ─────────────────────────────────────────────────────


class Platform(Enum):
    """Supported streaming platforms."""

    TWITCH = "twitch"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    KICK = "kick"
    OTHER = "other"


class Confidence(Enum):
    """Confidence level for a prediction score."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class QueueBand(Enum):
    """Scheduling queue priority band."""

    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"


class UiState(Enum):
    """UI-facing state label produced by the prediction engine."""

    IDLE = "idle"
    UPCOMING = "upcoming"
    EXPECTED_NOW = "expected_now"
    DELAYED = "delayed"
    LIVE = "live"
    COLD = "cold"
    DISABLED = "disabled"


class RecordingStatus(Enum):
    """Lifecycle status of a recording session."""

    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    SPLIT = "split"


class ArtifactType(Enum):
    """Type of file produced during a recording session."""

    RAW_TS = "raw_ts"
    RAW_MKV = "raw_mkv"
    FINAL_MP4 = "final_mp4"
    LOG = "log"


class ArtifactStatus(Enum):
    """Lifecycle status of a recording artifact."""

    WRITING = "writing"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class ContainerFormat(Enum):
    """Known container formats for recording artifacts."""

    TS = "ts"
    MKV = "mkv"
    MP4 = "mp4"
