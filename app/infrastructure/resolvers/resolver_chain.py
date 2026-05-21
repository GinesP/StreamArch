"""Chain of resolvers — tries each backend in order until one succeeds."""

from typing import Protocol

from app.infrastructure.resolvers.result import ResolveResult


class Resolver(Protocol):
    def resolve(self, url: str) -> ResolveResult: ...


class ResolverChain:
    """Tries resolvers in priority order.

    Iterates through the resolver list and returns the first result
    where ``is_live`` is ``True``.  Resolvers that have not been
    implemented yet raise ``NotImplementedError``, which the chain
    silently skips.
    """

    def __init__(self, resolvers: list[Resolver]) -> None:
        self._resolvers = resolvers

    def resolve(self, url: str) -> ResolveResult:
        for resolver in self._resolvers:
            try:
                result = resolver.resolve(url)
                if result.is_live:
                    return result
            except NotImplementedError:
                continue
        return ResolveResult(is_live=False)
