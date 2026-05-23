"""FileManager — handles recording file paths, naming, and retention.

Output files follow this naming scheme::

    {channel}_{title}_{YYYY-MM-DD}_{HH-MM-SS}.{ext}

When *stream_title* is empty or ``None`` the title segment is omitted::

    {channel}_{YYYY-MM-DD}_{HH-MM-SS}.{ext}

Example
-------
``allie-allieostudio_Love_Club_2026-05-22_23-12-56.ts``
"""

import re
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

# Characters forbidden in filenames across Windows, macOS, and Linux.
# Includes control characters (0x00-0x1F), reserved chars, and the
# Unicode replacement character that some systems inject.
_INVALID_FS_CHARS: re.Pattern = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class FileManager:
    """Manages file paths for recording artifacts.

    Parameters
    ----------
    base_path:
        Root directory for all recording files.
    per_stream_directory:
        Default value for per-stream directory placement.  Can be
        overridden per call to :meth:`allocate_path`.
    timezone:
        IANA timezone name (e.g. ``"America/New_York"``) used for
        filename date/time segments.  ``None`` or ``"UTC"`` means UTC.
    """

    def __init__(
        self,
        base_path: Path,
        per_stream_directory: bool = True,
        tz_name: str | None = None,
    ) -> None:
        self._base_path = base_path
        self._per_stream_directory = per_stream_directory
        # Parameter is named *tz_name* to avoid shadowing datetime.timezone.
        self._tz: timezone | zoneinfo.ZoneInfo = (
            zoneinfo.ZoneInfo(tz_name)
            if tz_name and tz_name.upper() != "UTC"
            else timezone.utc
        )

    def allocate_path(
        self,
        handle: str,
        extension: str = "ts",
        stream_title: str | None = None,
        per_stream_directory: bool | None = None,
    ) -> Path:
        """Generate a file path for a new recording.

        Creates the parent directory if it does not exist.

        Parameters
        ----------
        handle:
            Channel / streamer handle (appears as the first segment of
            the filename).
        extension:
            File extension without dot (e.g. ``"ts"``, ``"mp4"``).
        stream_title:
            Optional live-stream title.  Sanitised and inserted as the
            second filename segment when present.
        per_stream_directory:
            If ``True`` the file is placed under a sub-directory named
            after *handle*.  ``None`` (default) falls back to the
            instance-level default set in the constructor.

        Returns
        -------
        An absolute :class:`Path` like
        ``/data/recordings/allie-allieostudio/2026-05-22_23-12-56.ts``.
        """
        use_per_stream = (
            per_stream_directory
            if per_stream_directory is not None
            else self._per_stream_directory
        )

        now = datetime.now(self._tz)
        date_part = now.strftime("%Y-%m-%d")
        time_part = now.strftime("%H-%M-%S")

        # Build the filename segments.
        parts: list[str] = [_sanitise_filename(handle), date_part, time_part]
        if stream_title:
            title = _sanitise_filename(stream_title)
            if title:
                parts.insert(1, title)

        filename = "_".join(parts) + f".{extension}"

        if use_per_stream:
            sanitised_handle = _sanitise_filename(handle)
            filepath = self._base_path / sanitised_handle / filename
        else:
            filepath = self._base_path / filename

        filepath.parent.mkdir(parents=True, exist_ok=True)
        return filepath

    def ensure_directory(self) -> None:
        """Ensure the base recordings directory exists."""
        self._base_path.mkdir(parents=True, exist_ok=True)


# ── Module-level helpers ───────────────────────────────────────────────


def _sanitise_filename(text: str) -> str:
    """Strip filesystem-unsafe characters and normalise whitespace.

    * Removes characters invalid on Windows (``<>:"/\\|?*``), control
      codes, and the DEL character.
    * Replaces runs of whitespace with a single underscore.
    * Strips leading/trailing ``_``, ``.``, ``-`` and whitespace.
    """
    cleaned = _INVALID_FS_CHARS.sub("", text)
    # Collapse any whitespace into single underscores.
    cleaned = "_".join(cleaned.split())
    # Trim unsafe leading/trailing characters.
    return cleaned.strip("_. -\t\n\r\f\v")
