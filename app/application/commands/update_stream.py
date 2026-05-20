"""Update an existing stream target's configuration.

Only a practical subset of fields can be updated through this command.
Other mutations (schedule, recording state) are handled by dedicated
orchestrators.
"""

from datetime import datetime

from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)

# Fields that users are allowed to modify through this command.
# Other fields (id, platform, handle, created_at, etc.) are immutable
# after creation or managed by dedicated subsystems.
_UPDATABLE_FIELDS = frozenset({
    "display_name",
    "source_url",
    "preferred_quality",
    "output_profile_id",
    "schedule_mode",
    "enabled",
    "favorite",
})


# ── Command ────────────────────────────────────────────────────────────


class UpdateStreamCommand:
    """Request: modify one or more fields on an existing stream target."""

    def __init__(self, stream_id: str, **fields) -> None:
        self.stream_id = stream_id
        self.fields = fields


# ── Handler ────────────────────────────────────────────────────────────


class UpdateStreamHandler:
    """Handles :class:`UpdateStreamCommand` — validates and persists."""

    def __init__(self, stream_target_repo: StreamTargetRepository) -> None:
        self._repo = stream_target_repo

    def handle(self, cmd: UpdateStreamCommand) -> None:
        """Apply the requested field updates.

        Raises ``ValueError`` if the stream target does not exist or
        if unknown/non-updatable fields are included.
        """
        target = self._repo.get(cmd.stream_id)
        if target is None:
            raise ValueError(f"Stream target {cmd.stream_id!r} not found")

        unknown = set(cmd.fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValueError(
                f"Unknown or non-updatable fields: {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(sorted(_UPDATABLE_FIELDS))}"
            )

        # Build a kwargs dict with all current values, then override.
        kwargs = {
            f.name: getattr(target, f.name)
            for f in target.__dataclass_fields__.values()
        }

        for field, value in cmd.fields.items():
            if field in ("enabled", "favorite"):
                kwargs[field] = bool(value)
            elif field == "schedule_mode":
                kwargs[field] = ScheduleMode(value) if value is not None else ScheduleMode.NONE
            else:
                kwargs[field] = value

        kwargs["updated_at"] = datetime.utcnow()

        updated = StreamTarget(**kwargs)
        self._repo.save(updated)
