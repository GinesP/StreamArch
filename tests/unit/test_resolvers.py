"""Tests for cookie-aware resolvers with ``ResolveResult``.

Proves that each resolver:
- knows its assigned platform,
- returns the correct cookie string for that platform via
  ``get_cookie_string()``,
- returns ``""`` when no ``CookieService`` is provided,
- returns ``ResolveResult`` from ``resolve()``,
- the chain protocol works correctly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform
from app.infrastructure.resolvers.base import BaseResolver
from app.infrastructure.resolvers.resolver_chain import Resolver, ResolverChain
from app.infrastructure.resolvers.result import ResolveResult
from app.infrastructure.resolvers.streamget_resolver import StreamGetResolver
from app.infrastructure.resolvers.streamlink_resolver import StreamlinkResolver
from app.infrastructure.resolvers.ytdlp_resolver import YtDlpResolver


# ── Helpers ─────────────────────────────────────────────────────────────


class _ConcreteResolver(BaseResolver):
    """Minimal concrete subclass used to test base behaviour."""

    def resolve(self, url: str) -> ResolveResult:
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

    # ── resolve() — mocked streamget ──────────────────────────────────

    def test_resolve_returns_not_live_on_connection_error(self) -> None:
        """When streamget raises, resolve should gracefully return not live."""
        resolver = StreamGetResolver()

        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                side_effect=ConnectionError("Network error")
            )

            result = resolver.resolve("https://www.tiktok.com/@user/live")

        assert result.is_live is False
        assert result.stream_url is None
        assert result.title is None
        assert result.anchor_name is None
        assert result.m3u8_url is None

    def test_resolve_returns_not_live_when_offline(self) -> None:
        """Streamget returns StreamData with is_live=False."""
        resolver = StreamGetResolver()

        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                return_value={"live_url": "https://www.tiktok.com/@user/live"}
            )

            # Simulate a non-live StreamData
            mock_stream_data = MagicMock()
            mock_stream_data.is_live = False
            mock_stream_data.record_url = None
            mock_stream_data.flv_url = None
            mock_stream_data.title = "Offline Stream"
            mock_stream_data.anchor_name = "TestUser"
            mock_stream_data.m3u8_url = None
            mock_instance.fetch_stream_url = AsyncMock(return_value=mock_stream_data)

            result = resolver.resolve("https://www.tiktok.com/@user/live")

        assert result.is_live is False
        assert result.stream_url is None
        # Title/name are platform metadata, returned even when offline
        assert result.title == "Offline Stream"

    def test_resolve_returns_live_stream_result(self) -> None:
        """Full live-stream resolution — prefers FLV over HLS."""
        resolver = StreamGetResolver()

        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                return_value={"live_url": "https://www.tiktok.com/@user/live"}
            )

            mock_stream_data = MagicMock()
            mock_stream_data.is_live = True
            mock_stream_data.record_url = "https://example.com/stream.m3u8"
            mock_stream_data.flv_url = "https://example.com/stream.flv"
            mock_stream_data.title = "🎮 Gaming Stream"
            mock_stream_data.anchor_name = "TestUser-testuser"
            mock_stream_data.m3u8_url = "https://example.com/stream.m3u8"
            mock_instance.fetch_stream_url = AsyncMock(return_value=mock_stream_data)

            result = resolver.resolve("https://www.tiktok.com/@user/live")

        assert result.is_live is True
        assert result.stream_url == "https://example.com/stream.flv"
        assert result.flv_url == "https://example.com/stream.flv"
        assert result.title == "🎮 Gaming Stream"
        assert result.anchor_name == "TestUser-testuser"
        assert result.m3u8_url == "https://example.com/stream.m3u8"

    def test_resolve_falls_back_to_record_url_when_no_flv(self) -> None:
        """When flv_url is None, HLS record_url is used."""
        resolver = StreamGetResolver()

        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                return_value={"live_url": "https://www.tiktok.com/@user/live"}
            )

            mock_stream_data = MagicMock()
            mock_stream_data.is_live = True
            mock_stream_data.record_url = "https://example.com/stream.m3u8"
            mock_stream_data.flv_url = None
            mock_stream_data.title = "No FLV"
            mock_stream_data.anchor_name = "test"
            mock_stream_data.m3u8_url = "https://example.com/stream.m3u8"
            mock_instance.fetch_stream_url = AsyncMock(return_value=mock_stream_data)

            result = resolver.resolve("https://www.tiktok.com/@user/live")

        assert result.is_live is True
        assert result.stream_url == "https://example.com/stream.m3u8"
        assert result.flv_url is None

    def test_resolve_handles_missing_flv_url(self) -> None:
        """When stream_data lacks flv_url, stream_url falls back to record_url."""
        resolver = StreamGetResolver()

        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                return_value={"live_url": "https://www.tiktok.com/@user/live"}
            )

            mock_stream_data = MagicMock()
            mock_stream_data.is_live = True
            mock_stream_data.record_url = "https://example.com/stream.m3u8"
            del mock_stream_data.flv_url  # simulate missing attribute
            mock_stream_data.title = "No FLV attr"
            mock_stream_data.anchor_name = "test"
            mock_stream_data.m3u8_url = "https://example.com/stream.m3u8"
            mock_instance.fetch_stream_url = AsyncMock(return_value=mock_stream_data)

            result = resolver.resolve("https://www.tiktok.com/@user/live")

        assert result.is_live is True
        assert result.stream_url == "https://example.com/stream.m3u8"
        assert result.flv_url is None

    def test_resolve_passes_cookies_to_streamget(self) -> None:
        """Cookies from the cookie service are passed to TikTokLiveStream."""
        svc = _fake_service(tiktok="sessionid=abc123")
        resolver = StreamGetResolver(svc)

        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                return_value={"live_url": "https://www.tiktok.com/@user/live"}
            )
            mock_stream_data = MagicMock()
            mock_stream_data.is_live = False
            mock_stream_data.record_url = None
            mock_stream_data.flv_url = None
            mock_stream_data.title = None
            mock_stream_data.anchor_name = None
            mock_stream_data.m3u8_url = None
            mock_instance.fetch_stream_url = AsyncMock(return_value=mock_stream_data)

            resolver.resolve("https://www.tiktok.com/@user/live")

        mock_cls.assert_called_once_with(cookies="sessionid=abc123")

    def test_satisfies_resolver_protocol(self) -> None:
        """Structural check: the resolver matches the Resolver protocol."""
        # Protocol conformance is structural — resolve(str) -> ResolveResult
        assert hasattr(StreamGetResolver, "resolve")
        # Check that resolve returns a ResolveResult at runtime
        resolver = StreamGetResolver()
        with patch("streamget.TikTokLiveStream") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            mock_instance.fetch_web_stream_data = AsyncMock(
                return_value={"live_url": "url"}
            )
            mock_stream_data = MagicMock()
            mock_stream_data.is_live = False
            mock_stream_data.record_url = None
            mock_stream_data.flv_url = None
            mock_stream_data.title = None
            mock_stream_data.anchor_name = None
            mock_stream_data.m3u8_url = None
            mock_instance.fetch_stream_url = AsyncMock(return_value=mock_stream_data)

            result = resolver.resolve("https://tiktok.com/@user")

        assert isinstance(result, ResolveResult)


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


# ── ResolverChain ───────────────────────────────────────────────────────


class TestResolverChain:
    def test_returns_first_live_result(self) -> None:
        r1 = MagicMock()
        r1.resolve.return_value = ResolveResult(is_live=False)
        r2 = MagicMock()
        r2.resolve.return_value = ResolveResult(
            is_live=True,
            stream_url="https://live.example.com/stream",
            title="Second Stream",
        )

        chain = ResolverChain([r1, r2])
        result = chain.resolve("https://example.com/stream")

        assert result.is_live is True
        assert result.stream_url == "https://live.example.com/stream"
        assert result.title == "Second Stream"

    def test_skips_not_implemented_resolvers(self) -> None:
        r1 = MagicMock()
        r1.resolve.side_effect = NotImplementedError
        r2 = MagicMock()
        r2.resolve.return_value = ResolveResult(is_live=True, stream_url="url2")

        chain = ResolverChain([r1, r2])
        result = chain.resolve("https://example.com/stream")

        assert result.is_live is True
        assert result.stream_url == "url2"

    def test_skips_non_live_to_reach_live(self) -> None:
        r1 = MagicMock()
        r1.resolve.return_value = ResolveResult(is_live=False)
        r2 = MagicMock()
        r2.resolve.return_value = ResolveResult(is_live=False)
        r3 = MagicMock()
        r3.resolve.return_value = ResolveResult(is_live=True, stream_url="url3")

        chain = ResolverChain([r1, r2, r3])
        result = chain.resolve("https://example.com/stream")

        assert result.is_live is True
        assert result.stream_url == "url3"

    def test_returns_not_live_when_none_live(self) -> None:
        r1 = MagicMock()
        r1.resolve.return_value = ResolveResult(is_live=False)

        chain = ResolverChain([r1])
        result = chain.resolve("https://example.com/stream")

        assert result.is_live is False
        assert result.stream_url is None

    def test_returns_not_live_on_mixed_failures(self) -> None:
        r1 = MagicMock()
        r1.resolve.side_effect = NotImplementedError
        r2 = MagicMock()
        r2.resolve.return_value = ResolveResult(is_live=False)

        chain = ResolverChain([r1, r2])
        result = chain.resolve("https://example.com/stream")

        assert result.is_live is False

    def test_empty_chain_returns_not_live(self) -> None:
        chain = ResolverChain([])
        result = chain.resolve("https://example.com/stream")

        assert result.is_live is False

    def test_stops_after_first_live_does_not_call_remaining(self) -> None:
        r1 = MagicMock()
        r1.resolve.return_value = ResolveResult(is_live=True, stream_url="url1")
        r2 = MagicMock()

        chain = ResolverChain([r1, r2])
        chain.resolve("https://example.com/stream")

        r1.resolve.assert_called_once()
        r2.resolve.assert_not_called()


# ── ResolveResult dataclass ─────────────────────────────────────────────


class TestResolveResult:
    def test_defaults_are_false_and_none(self) -> None:
        result = ResolveResult()
        assert result.is_live is False
        assert result.stream_url is None
        assert result.title is None
        assert result.anchor_name is None
        assert result.m3u8_url is None

    def test_can_set_all_fields(self) -> None:
        result = ResolveResult(
            is_live=True,
            stream_url="https://example.com/record.m3u8",
            title="Live Stream",
            anchor_name="Streamer",
            m3u8_url="https://example.com/stream.m3u8",
        )
        assert result.is_live is True
        assert result.stream_url == "https://example.com/record.m3u8"
        assert result.title == "Live Stream"
        assert result.anchor_name == "Streamer"
        assert result.m3u8_url == "https://example.com/stream.m3u8"

    def test_is_dataclass(self) -> None:
        """Verify that ResolveResult behaves as a dataclass (equality, repr)."""
        a = ResolveResult(is_live=True, stream_url="url")
        b = ResolveResult(is_live=True, stream_url="url")
        assert a == b

        c = ResolveResult(is_live=False)
        assert a != c
