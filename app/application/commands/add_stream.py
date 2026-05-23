"""Add a new stream target to monitoring.

Creates a :class:`StreamTarget` entity.  The monitoring cycle will
create an in-memory snapshot when it first sees the target.
"""

import uuid

from app.domain.shared.types import Platform, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)

# ── Command ────────────────────────────────────────────────────────────


class AddStreamCommand:
    """Request: register a new stream target."""

    def __init__(
        self,
        platform: str,
        handle: str,
        source_url: str,
        display_name: str,
        preferred_quality: str | None = None,
        output_profile_id: str | None = None,
        schedule_mode: str | None = None,
    ) -> None:
        self.platform = platform
        self.handle = handle
        self.source_url = source_url
        self.display_name = display_name
        self.preferred_quality = preferred_quality
        self.output_profile_id = output_profile_id
        self.schedule_mode = schedule_mode


# ── Validation ─────────────────────────────────────────────────────────

_VALID_PLATFORMS = {p.value for p in Platform}
_VALID_SCHEDULE_MODES = {m.value for m in ScheduleMode}


def _validate(cmd: AddStreamCommand) -> None:
    if cmd.platform not in _VALID_PLATFORMS:
        raise ValueError(
            f"Invalid platform {cmd.platform!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_PLATFORMS))}"
        )
    if not cmd.handle or not cmd.handle.strip():
        raise ValueError("handle must not be empty")
    if not cmd.source_url or not cmd.source_url.strip():
        raise ValueError("source_url must not be empty")
    if not cmd.display_name or not cmd.display_name.strip():
        raise ValueError("display_name must not be empty")
    if cmd.schedule_mode is not None and cmd.schedule_mode not in _VALID_SCHEDULE_MODES:
        raise ValueError(
            f"Invalid schedule_mode {cmd.schedule_mode!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_SCHEDULE_MODES))}"
        )


# ── Handler ────────────────────────────────────────────────────────────


class AddStreamHandler:
    """Handles :class:`AddStreamCommand` — validates and persists."""

    def __init__(
        self,
        stream_target_repo: StreamTargetRepository,
    ) -> None:
        self._target_repo = stream_target_repo

    def handle(self, cmd: AddStreamCommand) -> str:
        """Execute and return the new stream target id."""
        _validate(cmd)

        # Prevent duplicate creation — uniqueness defined as (platform, handle).
        existing = self._target_repo.find_by_platform_handle(cmd.platform, cmd.handle)
        if existing is not None:
            raise ValueError(
                f"A stream target for {cmd.platform}/{cmd.handle.strip()} "
                f"already exists (id={existing.id})"
            )

        now = utc_now()
        target_id = str(uuid.uuid4())

        target = StreamTarget(
            id=target_id,
            platform=Platform(cmd.platform),
            handle=cmd.handle.strip(),
            source_url=cmd.source_url.strip(),
            display_name=cmd.display_name.strip(),
            enabled=True,
            favorite=False,
            preferred_quality=cmd.preferred_quality,
            output_profile_id=cmd.output_profile_id,
            schedule_mode=(
                ScheduleMode(cmd.schedule_mode) if cmd.schedule_mode else ScheduleMode.NONE
            ),
            created_at=now,
            updated_at=now,
        )

        self._target_repo.save(target)
        return target_id
