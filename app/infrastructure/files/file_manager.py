"""FileManager — handles recording file paths, naming, and retention."""

from pathlib import Path


class FileManager:
    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path

    def allocate_path(self, handle: str, extension: str = "ts") -> Path:
        """Generate a unique file path for a new recording."""
        raise NotImplementedError

    def ensure_directory(self) -> None:
        self._base_path.mkdir(parents=True, exist_ok=True)
