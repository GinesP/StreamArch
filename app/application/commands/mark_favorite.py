"""Toggle favorite status for a stream target."""


class MarkFavoriteCommand:
    def __init__(self, stream_id: str, favorite: bool) -> None:
        self.stream_id = stream_id
        self.favorite = favorite


class MarkFavoriteHandler:
    def handle(self, cmd: MarkFavoriteCommand) -> None:
        raise NotImplementedError
