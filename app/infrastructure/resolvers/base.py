"""Base resolver with platform awareness and cookie access.

Every concrete resolver knows *which platform* it resolves and can
obtain the authentication cookie string for that platform via a
shared ``CookieService`` reference.

Subclasses override ``resolve()`` and call ``self.get_cookie_string()``
when the downstream tool needs authentication cookies::

    class MyResolver(BaseResolver):
        def resolve(self, url: str) -> str | None:
            cookies = self.get_cookie_string()
            # ... hand cookies to the tool ...
            return None
"""

from app.application.services.cookie_service import CookieService
from app.domain.shared.types import Platform


class BaseResolver:
    """Skeletal base resolver that knows its platform and can access cookies.

    Parameters
    ----------
    platform:
        The :class:`Platform` enum value this resolver handles (e.g.
        ``Platform.TWITCH``).
    cookie_service:
        Optional application-level cookie service. When provided,
        ``self.get_cookie_string()`` returns the stored cookie string
        for ``platform``. When ``None`` it returns ``""`` — useful
        for contexts (e.g. early integration tests) that don't need
        cookies yet.
    """

    def __init__(
        self,
        platform: Platform,
        cookie_service: CookieService | None = None,
    ) -> None:
        self._platform = platform
        self._cookie_service = cookie_service

    def get_cookie_string(self) -> str:
        """Return the ``name=value; ...`` cookie string for this resolver's
        platform.

        Returns ``""`` when the platform has no stored cookies or when
        the resolver was constructed without a ``CookieService``.
        """
        if self._cookie_service is None:
            return ""
        return self._cookie_service.get_cookie_string(self._platform.value)

    def resolve(self, url: str) -> str | None:
        """Resolve *url* to a playable stream URI.

        Subclasses MUST override this method.
        """
        raise NotImplementedError
