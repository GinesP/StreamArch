"""Tests for cookie storage infrastructure and application service."""

import json
import os
from pathlib import Path

import pytest

from app.application.services.cookie_service import CookieService
from app.infrastructure.cookies.cookie_storage import CookieEntry, CookieStore

# ── Sample import data ─────────────────────────────────────────────────

SAMPLE_PUPPETEER_JSON = [
    {
        "name": "sessionid",
        "value": "abc123",
        "domain": ".twitch.tv",
        "path": "/",
        "httpOnly": True,
        "secure": True,
    },
    {
        "name": "persistent",
        "value": "xyz789",
        "domain": ".twitch.tv",
        "path": "/",
        "httpOnly": True,
        "secure": True,
    },
    {
        "name": "login_token",
        "value": "tok_42",
        "domain": "twitch.tv",
        "path": "/",
        "httpOnly": False,
        "secure": False,
    },
]

SAMPLE_NON_PLATFORM_JSON = [
    {
        "name": "test_cookie",
        "value": "test_val",
        "domain": ".example.com",
    },
]


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> CookieStore:
    return CookieStore(base_dir=str(tmp_path / "cookies"))


@pytest.fixture
def puppy_json(tmp_path: Path) -> str:
    path = tmp_path / "export.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(SAMPLE_PUPPETEER_JSON, f)
    return str(path)


# ── CookieEntry tests ──────────────────────────────────────────────────


class TestCookieEntry:
    def test_minimal_entry(self) -> None:
        e = CookieEntry(name="a", value="b")
        assert e.name == "a"
        assert e.value == "b"
        assert e.domain is None

    def test_full_entry(self) -> None:
        e = CookieEntry(
            name="x", value="y", domain=".x.com",
            path="/", http_only=True, secure=True,
        )
        assert e.name == "x"
        assert e.secure is True


# ── CookieStore tests ──────────────────────────────────────────────────


class TestCookieStore:
    def test_get_cookie_string_empty_when_no_file(self, store: CookieStore) -> None:
        assert store.get_cookie_string("twitch") == ""

    def test_get_cookies_empty_when_no_file(self, store: CookieStore) -> None:
        assert store.get_cookies("twitch") == []

    def test_set_and_get_round_trip(self, store: CookieStore) -> None:
        entries = [
            CookieEntry(name="a", value="1"),
            CookieEntry(name="b", value="2"),
        ]
        store.set_cookies("twitch", entries)

        cookie_str = store.get_cookie_string("twitch")
        assert cookie_str == "a=1; b=2"

    def test_set_and_get_entries(self, store: CookieStore) -> None:
        entries = [
            CookieEntry(name="a", value="1", domain=".twitch.tv"),
        ]
        store.set_cookies("twitch", entries)

        retrieved = store.get_cookies("twitch")
        assert len(retrieved) == 1
        assert retrieved[0].name == "a"
        assert retrieved[0].value == "1"
        assert retrieved[0].domain == ".twitch.tv"

    def test_overwrite_existing(self, store: CookieStore) -> None:
        store.set_cookies("twitch", [CookieEntry(name="a", value="1")])
        store.set_cookies("twitch", [CookieEntry(name="b", value="2")])

        assert store.get_cookie_string("twitch") == "b=2"

    def test_import_from_json(self, store: CookieStore, puppy_json: str) -> None:
        entries = store.import_from_json("twitch", puppy_json)
        assert len(entries) == 3

        cookie_str = store.get_cookie_string("twitch")
        assert "sessionid=abc123" in cookie_str
        assert "persistent=xyz789" in cookie_str
        assert "login_token=tok_42" in cookie_str

    def test_import_preserves_optional_fields(
        self, store: CookieStore, puppy_json: str
    ) -> None:
        entries = store.import_from_json("twitch", puppy_json)
        session = next(e for e in entries if e.name == "sessionid")
        assert session.domain == ".twitch.tv"
        assert session.path == "/"
        assert session.http_only is True
        assert session.secure is True

        login = next(e for e in entries if e.name == "login_token")
        assert login.http_only is False
        assert login.secure is False

    def test_import_from_nonexistent_file_raises(
        self, store: CookieStore
    ) -> None:
        with pytest.raises(FileNotFoundError):
            store.import_from_json("twitch", "/nonexistent/file.json")

    def test_remove(self, store: CookieStore) -> None:
        store.set_cookies("twitch", [CookieEntry(name="a", value="1")])
        assert store.get_cookie_string("twitch") == "a=1"

        store.remove("twitch")
        assert store.get_cookie_string("twitch") == ""

    def test_remove_missing_does_not_raise(self, store: CookieStore) -> None:
        store.remove("nonexistent")  # should not raise

    def test_list_platforms(self, store: CookieStore) -> None:
        assert store.list_platforms() == []

        store.set_cookies("twitch", [CookieEntry(name="a", value="1")])
        store.set_cookies("youtube", [CookieEntry(name="b", value="2")])
        store.set_cookies("tiktok", [CookieEntry(name="c", value="3")])

        platforms = store.list_platforms()
        assert platforms == ["tiktok", "twitch", "youtube"]

    def test_atomic_write_leaves_valid_file(self, store: CookieStore) -> None:
        """Even after multiple writes, the file must be valid JSON."""
        for i in range(5):
            store.set_cookies(
                "twitch", [CookieEntry(name="count", value=str(i))]
            )

        data = json.loads(
            (store._file_path("twitch")).read_text(encoding="utf-8")
        )
        assert data["cookie_string"] == "count=4"

    def test_platforms_isolated(self, store: CookieStore) -> None:
        store.set_cookies("twitch", [CookieEntry(name="a", value="1")])
        store.set_cookies("youtube", [CookieEntry(name="b", value="2")])

        assert store.get_cookie_string("twitch") == "a=1"
        assert store.get_cookie_string("youtube") == "b=2"

    def test_empty_cookie_list(self, store: CookieStore) -> None:
        """Setting an empty cookie list should produce an empty string."""
        store.set_cookies("twitch", [])
        assert store.get_cookie_string("twitch") == ""
        assert store.get_cookies("twitch") == []

    def test_path_contains_special_chars(self, store: CookieStore) -> None:
        """Platform names with special chars work (e.g. domains)."""
        store.set_cookies(
            "some-platform.test", [CookieEntry(name="a", value="b")]
        )
        assert store.get_cookie_string("some-platform.test") == "a=b"
        assert "some-platform.test" in store.list_platforms()


# ── CookieService tests ────────────────────────────────────────────────


class TestCookieService:
    @pytest.fixture
    def service(self, store: CookieStore) -> CookieService:
        return CookieService(store)

    def test_get_cookie_string_empty(self, service: CookieService) -> None:
        assert service.get_cookie_string("twitch") == ""

    def test_import_cookies(
        self, service: CookieService, puppy_json: str
    ) -> None:
        count = service.import_cookies("twitch", puppy_json)
        assert count == 3
        assert service.get_cookie_string("twitch") != ""

    def test_set_cookie_appends(self, service: CookieService) -> None:
        service.set_cookie("twitch", "a", "1")
        service.set_cookie("twitch", "b", "2")

        assert service.get_cookie_string("twitch") == "a=1; b=2"

    def test_set_cookie_updates_existing(self, service: CookieService) -> None:
        service.set_cookie("twitch", "a", "1")
        service.set_cookie("twitch", "a", "updated")

        assert service.get_cookie_string("twitch") == "a=updated"

    def test_list_platforms_empty(self, service: CookieService) -> None:
        assert service.list_platforms() == []

    def test_list_platforms_after_import(
        self, service: CookieService, puppy_json: str
    ) -> None:
        service.import_cookies("twitch", puppy_json)
        service.set_cookie("youtube", "x", "y")

        assert "twitch" in service.list_platforms()
        assert "youtube" in service.list_platforms()
