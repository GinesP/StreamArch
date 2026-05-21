"""Tests for cookie-aware resolvers.

Proves that each resolver:
- knows its assigned platform,
- returns the correct cookie string for that platform via
  ``get_cookie_string()``,
- returns ``""`` when no ``CookieService`` is provided,
- raises ``NotImplementedError`` from ``resolve()`` (still skeletal).
"""

from unittest.mock import MagicMock

import pytest

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform
from app.infrastructure.resolvers.base import BaseResolver
from app.infrastructure.resolvers.streamget_resolver import StreamGetResolver
from app.infrastructure.resolvers.streamlink_resolver import StreamlinkResolver
from app.infrastructure.resolvers.ytdlp_resolver import YtDlpResolver


# ── Helpers ─────────────────────────────────────────────────────────────


class _ConcreteResolver(BaseResolver):
    """Minimal concrete subclass used to test base behaviour."""

    def resolve(self, url: str) -> str | None:
        # Satisfy the contract; override provides a safe default.
        return super().resolve(url)


def _fake_service(**mapping: str) -> CookieService:
    """Build a ``CookieService`` whose ``get_cookie_string`` returns the
    given *mapping* values.

    Usage::

        svc = _fake_service(twitch="t_sess=1", youtube="y_sess=2")
        svc.get_cookie_string("twitch")  # → "t_sess=1"
    """
    service = MagicMock(spec=CookieService)
    service.get_cookie_string.side_effect = mapping.get
    return service


# ── BaseResolver ────────────────────────────────────────────────────────


class TestBaseResolver:
    def test_no_cookie_service_returns_empty_string(self) -> None:
        resolver = _ConcreteResolver(Platform.TWITCH)
        assert resolver.get_cookie_string() == ""

    def test_returns_cookie_for_its_platform(self) -> None:
        service = _fake_service(twitch="session=abc")
        resolver = _ConcreteResolver(Platform.TWITCH, service)

        result = resolver.get_cookie_string()

        assert result == "session=abc"

    def test_queries_correct_platform_name(self) -> None:
        service = MagicMock(spec=CookieService)
        service.get_cookie_string.return_value = "tok=xyz"
        resolver = _ConcreteResolver(Platform.YOUTUBE, service)

        resolver.get_cookie_string()

        service.get_cookie_string.assert_called_once_with("youtube")

    def test_different_platforms_return_different_cookies(self) -> None:
        service = _fake_service(twitch="t=1", tiktok="tk=2")
        tw = _ConcreteResolver(Platform.TWITCH, service)
        tt = _ConcreteResolver(Platform.TIKTOK, service)

        assert tw.get_cookie_string() == "t=1"
        assert tt.get_cookie_string() == "tk=2"

    def test_resolve_raises_not_implemented(self) -> None:
        resolver = _ConcreteResolver(Platform.TWITCH)
        with pytest.raises(NotImplementedError):
            resolver.resolve("https://twitch.tv/user")


# ── StreamGetResolver (TikTok) ──────────────────────────────────────────


class TestStreamGetResolver:
    def test_baked_platform_is_tiktok(self) -> None:
        svc = _fake_service(tiktok="sess=abc")
        resolver = StreamGetResolver(svc)
        assert resolver.get_cookie_string() == "sess=abc"

    def test_queries_tiktok_platform(self) -> None:
        svc = MagicMock(spec=CookieService)
        resolver = StreamGetResolver(svc)

        resolver.get_cookie_string()

        svc.get_cookie_string.assert_called_once_with("tiktok")

    def test_no_cookie_service(self) -> None:
        resolver = StreamGetResolver()
        assert resolver.get_cookie_string() == ""

    def test_resolve_still_skeletal(self) -> None:
        resolver = StreamGetResolver()
        with pytest.raises(NotImplementedError):
            resolver.resolve("https://tiktok.com/@user")

    def test_satisfies_resolver_protocol(self) -> None:
        """Structural check: the resolver matches the Resolver protocol."""
        # Protocol conformance is structural — resolve(str) -> str | None
        assert hasattr(StreamGetResolver, "resolve")


# ── StreamlinkResolver (Twitch) ─────────────────────────────────────────


class TestStreamlinkResolver:
    def test_baked_platform_is_twitch(self) -> None:
        svc = _fake_service(twitch="sess=abc")
        resolver = StreamlinkResolver(svc)
        assert resolver.get_cookie_string() == "sess=abc"

    def test_queries_twitch_platform(self) -> None:
        svc = MagicMock(spec=CookieService)
        resolver = StreamlinkResolver(svc)

        resolver.get_cookie_string()

        svc.get_cookie_string.assert_called_once_with("twitch")

    def test_no_cookie_service(self) -> None:
        resolver = StreamlinkResolver()
        assert resolver.get_cookie_string() == ""

    def test_resolve_still_skeletal(self) -> None:
        resolver = StreamlinkResolver()
        with pytest.raises(NotImplementedError):
            resolver.resolve("https://twitch.tv/user")

    def test_satisfies_resolver_protocol(self) -> None:
        """Structural check: the resolver matches the Resolver protocol."""
        assert hasattr(StreamlinkResolver, "resolve")


# ── YtDlpResolver (YouTube) ─────────────────────────────────────────────


class TestYtDlpResolver:
    def test_baked_platform_is_youtube(self) -> None:
        svc = _fake_service(youtube="sess=abc")
        resolver = YtDlpResolver(svc)
        assert resolver.get_cookie_string() == "sess=abc"

    def test_queries_youtube_platform(self) -> None:
        svc = MagicMock(spec=CookieService)
        resolver = YtDlpResolver(svc)

        resolver.get_cookie_string()

        svc.get_cookie_string.assert_called_once_with("youtube")

    def test_no_cookie_service(self) -> None:
        resolver = YtDlpResolver()
        assert resolver.get_cookie_string() == ""

    def test_resolve_still_skeletal(self) -> None:
        resolver = YtDlpResolver()
        with pytest.raises(NotImplementedError):
            resolver.resolve("https://youtube.com/watch?v=xyz")

    def test_satisfies_resolver_protocol(self) -> None:
        """Structural check: the resolver matches the Resolver protocol."""
        assert hasattr(YtDlpResolver, "resolve")
