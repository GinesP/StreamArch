"""Chain of resolvers — tries each backend in order until one succeeds."""

from typing import Protocol


class Resolver(Protocol):
    def resolve(self, url: str) -> str | None: ...


class ResolverChain:
    """Tries resolvers in priority order."""

    def __init__(self, resolvers: list[Resolver]) -> None:
        self._resolvers = resolvers

    def resolve(self, url: str) -> str | None:
        for resolver in self._resolvers:
            result = resolver.resolve(url)
            if result is not None:
                return result
        return None
