"""Cookie storage — import, persist, and retrieve cookies by platform.

Uses JSON files under a configurable directory with atomic-write semantics.
One JSON file per platform:

    data/cookies/twitch.json
    data/cookies/youtube.json
    data/cookies/tiktok.json
    ...

File contents (example for ``twitch.json``):

.. code:: json

    {
        "cookies": [
            {"name": "sessionid", "value": "abc123", "domain": ".twitch.tv",
             "path": "/", "http_only": true, "secure": true}
        ],
        "cookie_string": "sessionid=abc123",
        "updated_at": "2026-05-21T12:00:00+00:00"
    }
"""

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Data types ─────────────────────────────────────────────────────────


@dataclass
class CookieEntry:
    """A single cookie with the fields that matter most."""

    name: str
    value: str
    domain: Optional[str] = None
    path: Optional[str] = None
    http_only: Optional[bool] = None
    secure: Optional[bool] = None


# ── Store ──────────────────────────────────────────────────────────────


class CookieStore:
    """Persists cookies per platform as JSON files with atomic writes.

    The store maintains one JSON file per platform under *base_dir*.
    Each file contains the raw cookie entries and a pre-computed
    ``cookie_string`` (``name=value; ...``) for quick consumption by
    resolvers, API handlers, or CLI tools.

    All mutation methods use atomic-write semantics — a crash mid-write
    never leaves a half-written file.
    """

    def __init__(self, base_dir: str | Path = "./data/cookies") -> None:
        self._base_dir = Path(base_dir)

    # ── Public read API ───────────────────────────────────────────

    def get_cookie_string(self, platform: str) -> str:
        """Return the ``name=value; ...`` string for *platform*.

        Returns ``""`` when no cookies have been stored for the platform.
        """
        path = self._file_path(platform)
        if not path.is_file():
            return ""
        data = self._read_file(path)
        return data.get("cookie_string", "")

    def get_cookies(self, platform: str) -> list[CookieEntry]:
        """Return the raw cookie entries for *platform*.

        Returns ``[]`` when no cookies have been stored.
        """
        path = self._file_path(platform)
        if not path.is_file():
            return []
        data = self._read_file(path)
        return [CookieEntry(**c) for c in data.get("cookies", [])]

    def list_platforms(self) -> list[str]:
        """Return platform names that have stored cookie files."""
        if not self._base_dir.is_dir():
            return []
        return sorted(
            f.stem
            for f in self._base_dir.iterdir()
            if f.suffix == ".json" and not f.stem.startswith(".")
        )

    # ── Public write API ──────────────────────────────────────────

    def set_cookies(self, platform: str, cookies: list[CookieEntry]) -> None:
        """Replace all cookies for *platform* and persist atomically."""
        cookie_string = "; ".join(f"{c.name}={c.value}" for c in cookies)
        payload = {
            "cookies": [asdict(c) for c in cookies],
            "cookie_string": cookie_string,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_file(self._file_path(platform), payload)

    def import_from_json(
        self, platform: str, json_path: str | Path
    ) -> list[CookieEntry]:
        """Import cookies from a Puppeteer-style JSON export file.

        The expected format is the one produced by the Chrome extension
        *Export cookie JSON file for Puppeteer*:

        .. code:: json

            [
                {
                    "name": "sessionid",
                    "value": "abc123",
                    "domain": ".twitch.tv",
                    "path": "/",
                    "httpOnly": true,
                    "secure": true
                }
            ]

        Returns the imported ``list[CookieEntry]`` for inspection.
        """
        with open(json_path, "r", encoding="utf-8") as f:
            raw: list[dict] = json.load(f)

        entries = [
            CookieEntry(
                name=item.get("name", ""),
                value=item.get("value", ""),
                domain=item.get("domain"),
                path=item.get("path"),
                http_only=item.get("httpOnly"),
                secure=item.get("secure"),
            )
            for item in raw
        ]
        self.set_cookies(platform, entries)
        return entries

    def remove(self, platform: str) -> None:
        """Delete the cookie file for *platform* if it exists."""
        path = self._file_path(platform)
        if path.is_file():
            path.unlink()

    # ── Internals ─────────────────────────────────────────────────

    def _file_path(self, platform: str) -> Path:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        return self._base_dir / f"{platform}.json"

    @staticmethod
    def _read_file(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_file(path: Path, payload: dict) -> None:
        """Write *payload* to *path* with atomic semantics.

        Writes to a temporary sibling file first, then renames over
        the target — a crash mid-write never leaves a half-written file.
        """
        tmp = path.with_suffix(f".tmp.{os.getpid()}")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp), str(path))
        finally:
            if tmp.is_file():
                tmp.unlink(missing_ok=True)
