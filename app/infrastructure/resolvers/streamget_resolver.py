"""StreamGet resolver — uses streamget binary to resolve stream URLs."""

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform
from .base import BaseResolver


class StreamGetResolver(BaseResolver):
    """TikTok resolver backed by the streamget binary.

    Parameters
    ----------
    cookie_service:
        Optional ``CookieService``. When provided the resolver can obtain
        the TikTok cookie string via ``self.get_cookie_string()``.
    """

    def __init__(self, cookie_service: CookieService | None = None) -> None:
        super().__init__(platform=Platform.TIKTOK, cookie_service=cookie_service)

    def resolve(self, url: str) -> str | None:
        """Resolve a stream URL to a playable stream URI."""
        raise NotImplementedError
