"""Streamlink resolver — uses streamlink to resolve stream URLs."""

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform
from .base import BaseResolver


class StreamlinkResolver(BaseResolver):
    """Twitch resolver backed by the streamlink CLI.

    Parameters
    ----------
    cookie_service:
        Optional ``CookieService``. When provided the resolver can obtain
        the Twitch cookie string via ``self.get_cookie_string()``.
    """

    def __init__(self, cookie_service: CookieService | None = None) -> None:
        super().__init__(platform=Platform.TWITCH, cookie_service=cookie_service)

    def resolve(self, url: str) -> str | None:
        raise NotImplementedError
