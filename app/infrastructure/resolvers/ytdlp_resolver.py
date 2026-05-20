"""yt-dlp resolver — uses yt-dlp to extract stream URLs."""


class YtDlpResolver:
    def resolve(self, url: str) -> str | None:
        raise NotImplementedError
