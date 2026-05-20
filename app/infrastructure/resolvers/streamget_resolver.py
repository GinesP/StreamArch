"""StreamGet resolver — uses streamget binary to resolve stream URLs."""


class StreamGetResolver:
    def resolve(self, url: str) -> str | None:
        """Resolve a stream URL to a playable stream URI."""
        raise NotImplementedError
