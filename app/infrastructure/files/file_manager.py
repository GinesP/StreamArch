"""FileManager — handles recording file paths, naming, and retention.

Uses a hierarchical directory layout under a configurable base path::

    {base_path}/{handle}/{date}_{short_uuid}.{extension}
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path


class FileManager:
    """Manages file paths for recording artifacts.

    Parameters
    ----------
    base_path:
        Root directory for all recording files.
    """

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path

    def allocate_path(self, handle: str, extension: str = "ts") -> Path:
        """Generate a unique file path for a new recording.

        Creates the parent directory if it does not exist.

        Args:
            handle: Streamer handle (used as a sub-directory name).
            extension: File extension without dot (e.g. ``"ts"``, ``"mp4"``).

        Returns:
            An absolute :class:`Path` like
            ``/data/recordings/streamer/20260522_a1b2c3d4.ts``.
        """
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{date_str}_{unique_id}.{extension}"
        filepath = self._base_path / handle / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        return filepath

    def ensure_directory(self) -> None:
        """Ensure the base recordings directory exists."""
        self._base_path.mkdir(parents=True, exist_ok=True)
