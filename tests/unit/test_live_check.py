"""Tests for LiveCheckService — resolves stream URLs via the resolver chain.

Covers:
- Resolving a live stream returns is_live=True with stream_url.
- Resolving a non-live stream returns is_live=False.
- Error handling (resolver chain returns not-live on failure).
- Target-not-found raises ValueError.
- Resolver result metadata is preserved.
"""

from unittest.mock import MagicMock

import pytest

from app.application.services.live_check_service import LiveCheckService
from app.domain.shared.types import Platform, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)
from app.infrastructure.resolvers.resolver_chain import ResolverChain
from app.infrastructure.resolvers.result import ResolveResult


# ── Helpers ─────────────────────────────────────────────────────────────


def _insert_target(repo: StreamTargetRepository, **overrides) -> str:
    now = utc_now()
    target = StreamTarget(
        id=overrides.get("id", "test-id"),
        platform=overrides.get("platform", Platform.TIKTOK),
        handle=overrides.get("handle", "tester"),
        source_url=overrides.get(
            "source_url", "https://www.tiktok.com/@tester/live"
        ),
        display_name=overrides.get("display_name", "Tester"),
        enabled=overrides.get("enabled", True),
        favorite=overrides.get("favorite", False),
        preferred_quality=overrides.get("preferred_quality", None),
        output_profile_id=overrides.get("output_profile_id", None),
        schedule_mode=overrides.get("schedule_mode", ScheduleMode.NONE),
        created_at=overrides.get("created_at", now),
        updated_at=overrides.get("updated_at", now),
    )
    repo.save(target)
    return target.id


def _make_service(
    target_repo: StreamTargetRepository,
    chain: ResolverChain | None = None,
) -> LiveCheckService:
    if chain is None:
        chain = ResolverChain([])
    return LiveCheckService(
        resolver_chain=chain,
        stream_target_repo=target_repo,
    )


@pytest.fixture
def db_path(tmp_path) -> str:
    path = tmp_path / "test.db"
    conn = get_connection(path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
    return str(path)


@pytest.fixture
def target_repo(db_path) -> StreamTargetRepository:
    return StreamTargetRepository(db_path)


# ── Tests ───────────────────────────────────────────────────────────────


class TestLiveCheckService:
    """Unit tests for LiveCheckService."""

    def test_live_stream_returns_resolve_result(
        self, target_repo,
    ) -> None:
        """When the resolver reports live, the result has is_live=True."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=True,
                stream_url="https://example.com/stream.m3u8",
                title="Live Now!",
                anchor_name="tester",
            ))),
        ])
        service = _make_service(target_repo, chain)

        result = service.check_stream(tid)

        assert result.is_live is True
        assert result.stream_url == "https://example.com/stream.m3u8"

    def test_offline_stream_returns_not_live(
        self, target_repo,
    ) -> None:
        """When the resolver reports not live, is_live is False."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
                title="Offline",
                anchor_name="tester",
            ))),
        ])
        service = _make_service(target_repo, chain)

        result = service.check_stream(tid)

        assert result.is_live is False

    def test_raises_on_missing_target(self, target_repo) -> None:
        """Checking a non-existent stream raises ValueError."""
        service = _make_service(target_repo)
        with pytest.raises(ValueError, match="not found"):
            service.check_stream("nonexistent")

    def test_resolver_returns_not_live_on_internal_error(
        self, target_repo,
    ) -> None:
        """When a resolver catches its own error and returns is_live=False,
        the chain propagates that result."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, chain)

        result = service.check_stream(tid)

        assert result.is_live is False

    def test_resolver_result_metadata_preserved(
        self, target_repo,
    ) -> None:
        """The full ResolveResult is returned with stream metadata."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=True,
                stream_url="https://example.com/stream.m3u8",
                title="Gaming Stream",
                anchor_name="ProGamer",
                m3u8_url="https://example.com/playlist.m3u8",
            ))),
        ])
        service = _make_service(target_repo, chain)

        result = service.check_stream(tid)

        assert result.stream_url == "https://example.com/stream.m3u8"
        assert result.title == "Gaming Stream"
        assert result.anchor_name == "ProGamer"
        assert result.m3u8_url == "https://example.com/playlist.m3u8"
