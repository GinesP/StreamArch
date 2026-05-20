"""Unmark a stream target as a favourite.

Removes the scheduling priority bias that favourited targets receive.
"""

from app.domain.shared.types import utc_now
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)


# ── Command ────────────────────────────────────────────────────────────


class UnmarkFavoriteCommand:
    """Request: unmark a stream target as a favourite."""

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id


# ── Handler ────────────────────────────────────────────────────────────


class UnmarkFavoriteHandler:
    """Handles :class:`UnmarkFavoriteCommand` — sets ``favorite = False``."""

    def __init__(self, stream_target_repo: StreamTargetRepository) -> None:
        self._repo = stream_target_repo

    def handle(self, cmd: UnmarkFavoriteCommand) -> None:
        """Unmark *stream_id* as favourite.

        Raises ``ValueError`` if the stream target does not exist.
        Idempotent — no-op if already not favourite.
        """
        target = self._repo.get(cmd.stream_id)
        if target is None:
            raise ValueError(f"Stream target {cmd.stream_id!r} not found")

        # Idempotent — already not favourite.
        if not target.favorite:
            return

        now = utc_now()

        kwargs = {
            f.name: getattr(target, f.name)
            for f in target.__dataclass_fields__.values()
        }
        kwargs["favorite"] = False
        kwargs["updated_at"] = now
        self._repo.save(target.__class__(**kwargs))
