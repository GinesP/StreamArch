"""CookieService — application-level facade over cookie storage.

Translates between domain primitives and infrastructure, keeping the
cookie store accessible to API handlers, resolvers, and CLI tools
without exposing disk I/O details.
"""

from app.infrastructure.cookies.cookie_storage import CookieEntry, CookieStore


class CookieService:
    """Application-level cookie operations.

    Usage::

        store = CookieStore("./data/cookies")
        service = CookieService(store)

        # Import from a browser export
        count = service.import_cookies("twitch", "twitch_cookies.json")

        # Use the cookie string in a resolver
        cookies = service.get_cookie_string("twitch")

        # Set a single cookie on the fly
        service.set_cookie("youtube", "SESSION", "abc123")
    """

    def __init__(self, store: CookieStore) -> None:
        self._store = store

    def get_cookie_string(self, platform: str) -> str:
        """Get the ``name=value; ...`` cookie string for *platform*.

        Returns ``""`` when no cookies have been stored.
        """
        return self._store.get_cookie_string(platform)

    def import_cookies(self, platform: str, json_path: str) -> int:
        """Import cookies from a Puppeteer-style JSON file.

        The file format matches the Chrome extension *Export cookie JSON
        file for Puppeteer*.

        Returns the number of cookies imported.
        """
        entries = self._store.import_from_json(platform, json_path)
        return len(entries)

    def set_cookie(self, platform: str, name: str, value: str) -> None:
        """Set a single cookie for *platform*, preserving existing ones.

        If a cookie with the same *name* already exists, its value is
        updated. Otherwise the new cookie is appended.
        """
        existing = self._store.get_cookies(platform)
        for i, c in enumerate(existing):
            if c.name == name:
                existing[i] = CookieEntry(name=name, value=value)
                break
        else:
            existing.append(CookieEntry(name=name, value=value))
        self._store.set_cookies(platform, existing)

    def list_platforms(self) -> list[str]:
        """Return platform names that have stored cookies."""
        return self._store.list_platforms()
