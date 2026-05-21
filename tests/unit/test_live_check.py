"""Tests for LiveCheckService — bridges resolvers with persistence.

Covers:
- Resolving a live stream and updating the snapshot to RECORDING.
- Resolving a non-live stream and updating the snapshot to IDLE.
- Error handling  (resolver chain returns not-live on failure).
- Target-not-found raises ValueError.
- First check creates a new snapshot.
- last_live_at is preserved on subsequent offline checks.
- timestamps (last_checked_at, updated_at) are set correctly.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.application.services.live_check_service import LiveCheckService
from app.domain.monitoring.snapshot import MonitoringSnapshot
from app.domain.monitoring.states import MonitoringState
from app.domain.shared.types import Confidence, Platform, QueueBand, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode
from app.infrastructure.db.connection import get_connection
from app.infrastructure.db.migrations import apply_migrations
from app.infrastructure.repositories.monitoring_snapshot_repository import (
    MonitoringSnapshotRepository,
)
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


def _insert_snapshot(
    repo: MonitoringSnapshotRepository, **overrides
) -> str:
    now = utc_now()
    snapshot = MonitoringSnapshot(
        stream_target_id=overrides["stream_target_id"],
        state=overrides.get("state", MonitoringState.IDLE),
        queue_band=overrides.get("queue_band", None),
        current_likelihood=overrides.get("current_likelihood", 0.5),
        current_confidence=overrides.get(
            "current_confidence", Confidence.MEDIUM
        ),
        next_check_at=overrides.get("next_check_at", None),
        last_checked_at=overrides.get("last_checked_at", None),
        last_live_at=overrides.get("last_live_at", None),
        current_recording_session_id=overrides.get(
            "current_recording_session_id", None
        ),
        last_error_code=overrides.get("last_error_code", None),
        last_error_message=overrides.get("last_error_message", None),
        updated_at=overrides.get("updated_at", now),
    )
    repo.save(snapshot)
    return snapshot.stream_target_id


def _make_service(
    target_repo: StreamTargetRepository,
    snapshot_repo: MonitoringSnapshotRepository,
    chain: ResolverChain | None = None,
) -> LiveCheckService:
    if chain is None:
        chain = ResolverChain([])
    return LiveCheckService(
        resolver_chain=chain,
        stream_target_repo=target_repo,
        monitoring_snapshot_repo=snapshot_repo,
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


@pytest.fixture
def snapshot_repo(db_path) -> MonitoringSnapshotRepository:
    return MonitoringSnapshotRepository(db_path)


# ── Tests ───────────────────────────────────────────────────────────────


class TestLiveCheckService:
    """Unit tests for LiveCheckService."""

    def test_live_stream_creates_recording_snapshot(
        self, target_repo, snapshot_repo
    ) -> None:
        """When the resolver reports live, the snapshot is set to RECORDING
        with likelihood=1.0 and last_live_at is recorded."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=True,
                stream_url="https://example.com/stream.m3u8",
                title="Live Now!",
                anchor_name="tester",
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        result = service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert result.is_live is True
        assert result.stream_url == "https://example.com/stream.m3u8"
        assert snapshot is not None
        assert snapshot.state == MonitoringState.RECORDING
        assert snapshot.current_likelihood == 1.0
        assert snapshot.last_live_at is not None

    def test_offline_stream_sets_idle_snapshot(
        self, target_repo, snapshot_repo
    ) -> None:
        """When the resolver reports not live, the snapshot is set to IDLE
        with likelihood=0.0."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
                title="Offline",
                anchor_name="tester",
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        result = service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert result.is_live is False
        assert snapshot is not None
        assert snapshot.state == MonitoringState.IDLE
        assert snapshot.current_likelihood == 0.0

    def test_raises_on_missing_target(
        self, target_repo, snapshot_repo
    ) -> None:
        """Checking a non-existent stream raises ValueError."""
        service = _make_service(target_repo, snapshot_repo)
        with pytest.raises(ValueError, match="not found"):
            service.check_stream("nonexistent")

    def test_resolver_returns_not_live_on_internal_error(
        self, target_repo, snapshot_repo
    ) -> None:
        """When a resolver catches its own error and returns is_live=False
        (e.g. StreamGetResolver catches exceptions), the chain propagates
        that result and the snapshot becomes IDLE."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        result = service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert result.is_live is False
        assert snapshot.state == MonitoringState.IDLE

    def test_first_check_creates_snapshot(
        self, target_repo, snapshot_repo
    ) -> None:
        """A stream target without a snapshot gets one created on first check."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        # No snapshot exists yet
        assert snapshot_repo.get(tid) is None

        service.check_stream(tid)

        snapshot = snapshot_repo.get(tid)
        assert snapshot is not None
        assert snapshot.stream_target_id == tid

    def test_preserves_last_live_at_on_subsequent_offline(
        self, target_repo, snapshot_repo
    ) -> None:
        """When a previously-live stream is now offline, last_live_at
        is preserved rather than cleared."""
        tid = _insert_target(target_repo)
        past_live = utc_now()
        _insert_snapshot(
            snapshot_repo,
            stream_target_id=tid,
            state=MonitoringState.RECORDING,
            current_likelihood=1.0,
            last_live_at=past_live,
        )

        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        # Freeze time so we can compare
        service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert snapshot.state == MonitoringState.IDLE
        assert snapshot.current_likelihood == 0.0
        assert snapshot.last_live_at == past_live  # preserved

    def test_updates_timestamps(
        self, target_repo, snapshot_repo
    ) -> None:
        """last_checked_at and updated_at are refreshed on every check."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert snapshot.last_checked_at is not None
        assert snapshot.updated_at is not None

    def test_sets_next_check_at(
        self, target_repo, snapshot_repo
    ) -> None:
        """next_check_at is set to a future timestamp after a check."""
        tid = _insert_target(target_repo)
        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert snapshot.next_check_at is not None
        assert snapshot.next_check_at > snapshot.last_checked_at

    def test_resets_queue_band_after_check(
        self, target_repo, snapshot_repo
    ) -> None:
        """The queue_band is cleared after a live check (scheduler re-assigns it)."""
        tid = _insert_target(target_repo)
        _insert_snapshot(
            snapshot_repo,
            stream_target_id=tid,
            state=MonitoringState.CHECKING,
            queue_band=QueueBand.FAST,
        )

        chain = ResolverChain([
            MagicMock(resolve=MagicMock(return_value=ResolveResult(
                is_live=False,
            ))),
        ])
        service = _make_service(target_repo, snapshot_repo, chain)

        service.check_stream(tid)
        snapshot = snapshot_repo.get(tid)

        assert snapshot.queue_band is None

    def test_resolver_result_metadata_preserved(
        self, target_repo, snapshot_repo
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
        service = _make_service(target_repo, snapshot_repo, chain)

        result = service.check_stream(tid)

        assert result.stream_url == "https://example.com/stream.m3u8"
        assert result.title == "Gaming Stream"
        assert result.anchor_name == "ProGamer"
        assert result.m3u8_url == "https://example.com/playlist.m3u8"
