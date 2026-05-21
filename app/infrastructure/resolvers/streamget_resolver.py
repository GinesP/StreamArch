"""StreamGet resolver — uses the streamget library to resolve TikTok URLs.

Usage::

    resolver = StreamGetResolver(cookie_service)
    result = resolver.resolve("https://www.tiktok.com/@user/live")
    if result.is_live:
        print(f"Live! URL: {result.stream_url}")
"""

import asyncio

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform
from app.infrastructure.resolvers.result import ResolveResult
from .base import BaseResolver


class StreamGetResolver(BaseResolver):
    """TikTok resolver backed by the streamget library.

    Parameters
    ----------
    cookie_service:
        Optional ``CookieService``. When provided the resolver can obtain
        the TikTok cookie string via ``self.get_cookie_string()``.
    """

    def __init__(self, cookie_service: CookieService | None = None) -> None:
        super().__init__(platform=Platform.TIKTOK, cookie_service=cookie_service)

    def resolve(self, url: str) -> ResolveResult:
        """Resolve a TikTok live URL using streamget.

        Uses ``asyncio.run()`` to bridge streamget's async API from our
        synchronous resolver.  The ``streamget`` import is kept inside the
        method so tests can mock it easily.
        """
        import streamget  # lazy — allows mocking in tests

        try:
            stream = streamget.TikTokLiveStream(cookies=self.get_cookie_string())
            json_data = asyncio.run(stream.fetch_web_stream_data(url=url))
            stream_data = asyncio.run(stream.fetch_stream_url(json_data, video_quality=None))

            return ResolveResult(
                is_live=stream_data.is_live,
                stream_url=stream_data.record_url,
                title=stream_data.title,
                anchor_name=stream_data.anchor_name,
                m3u8_url=stream_data.m3u8_url,
            )
        except NotImplementedError:
            raise
        except Exception:
            return ResolveResult(is_live=False)
