"""yt-dlp resolver — uses yt-dlp to extract stream URLs."""

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform
from app.infrastructure.resolvers.result import ResolveResult
from .base import BaseResolver


class YtDlpResolver(BaseResolver):
    """YouTube resolver backed by the yt-dlp CLI.

    Parameters
    ----------
    cookie_service:
        Optional ``CookieService``. When provided the resolver can obtain
        the YouTube cookie string via ``self.get_cookie_string()``.
    """

    def __init__(self, cookie_service: CookieService | None = None) -> None:
        super().__init__(platform=Platform.YOUTUBE, cookie_service=cookie_service)

    def resolve(self, url: str) -> ResolveResult:
        raise NotImplementedError
