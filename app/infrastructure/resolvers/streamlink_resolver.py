"""Streamlink resolver — uses streamlink to resolve stream URLs."""


class StreamlinkResolver:
    def resolve(self, url: str) -> str | None:
        raise NotImplementedError
