"""Tests for RecordingService — the orchestrator that coordinates ffmpeg
recording with session and artifact lifecycle.

All external dependencies (runner, file manager, repos, event bus) are
mocked so these tests are fast and deterministic.

Snapshots are no longer managed by RecordingService — the monitoring
cycle owns in-memory snapshots.  This test only verifies the recording
lifecycle (sessions, artifacts, ffmpeg, events).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.services.recording_service import RecordingService
from app.domain.recording.config import RecordingConfig
from app.domain.shared.types import ArtifactType, ContainerFormat, Platform, utc_now
from app.domain.stream_target.entities import StreamTarget
from app.domain.stream_target.value_objects import ScheduleMode


# ── Helpers ─────────────────────────────────────────────────────────────


NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


def _target(**overrides) -> StreamTarget:
    return StreamTarget(
        id=overrides.get("id", "t1"),
        platform=overrides.get("platform", Platform.TWITCH),
        handle=overrides.get("handle", "streamer"),
        source_url=overrides.get("source_url", "https://twitch.tv/streamer"),
        display_name=overrides.get("display_name", "Streamer"),
        enabled=overrides.get("enabled", True),
        favorite=overrides.get("favorite", False),
        preferred_quality=overrides.get("preferred_quality", None),
        output_profile_id=overrides.get("output_profile_id", None),
        schedule_mode=overrides.get("schedule_mode", ScheduleMode.NONE),
        created_at=overrides.get("created_at", NOW),
        updated_at=overrides.get("updated_at", NOW),
    )


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> MagicMock:
    mock = MagicMock()
    mock.start_recording.return_value = "runner-recording-id-123"
    return mock


@pytest.fixture
def file_manager() -> MagicMock:
    mock = MagicMock()
    mock.allocate_path.return_value = Path("/data/recordings/streamer/20260522_abcd.ts")
    return mock


@pytest.fixture
def session_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def artifact_repo() -> MagicMock:
    mock = MagicMock()
    mock.list_by_session.return_value = []
    return mock


@pytest.fixture
def target_repo() -> MagicMock:
    mock = MagicMock()
    mock.get.return_value = _target()
    return mock


@pytest.fixture
def event_bus() -> MagicMock:
    return MagicMock()


@pytest.fixture
def service(
    runner: MagicMock,
    file_manager: MagicMock,
    session_repo: MagicMock,
    artifact_repo: MagicMock,
    target_repo: MagicMock,
    event_bus: MagicMock,
) -> RecordingService:
    return RecordingService(
        runner=runner,
        file_manager=file_manager,
        session_repo=session_repo,
        artifact_repo=artifact_repo,
        target_repo=target_repo,
        event_bus=event_bus,
    )


@pytest.fixture
def cookie_service() -> MagicMock:
    mock = MagicMock()
    mock.get_cookie_string.return_value = "sessionid=abc123; csrftoken=xyz"
    return mock


@pytest.fixture
def service_with_config(
    runner: MagicMock,
    file_manager: MagicMock,
    session_repo: MagicMock,
    artifact_repo: MagicMock,
    target_repo: MagicMock,
    event_bus: MagicMock,
) -> RecordingService:
    return RecordingService(
        runner=runner,
        file_manager=file_manager,
        session_repo=session_repo,
        artifact_repo=artifact_repo,
        target_repo=target_repo,
        event_bus=event_bus,
        recording_config=RecordingConfig(
            segment_enabled=False,
            segment_time_seconds=1800,
            per_stream_directory=False,
            convert_to_mp4=True,
        ),
    )


@pytest.fixture
def service_with_cookies(
    runner: MagicMock,
    file_manager: MagicMock,
    session_repo: MagicMock,
    artifact_repo: MagicMock,
    target_repo: MagicMock,
    event_bus: MagicMock,
    cookie_service: MagicMock,
) -> RecordingService:
    return RecordingService(
        runner=runner,
        file_manager=file_manager,
        session_repo=session_repo,
        artifact_repo=artifact_repo,
        target_repo=target_repo,
        event_bus=event_bus,
        cookie_service=cookie_service,
    )


# ======================================================================
# Start Recording
# ======================================================================


class TestStartRecording:
    """RecordingService.start_recording — happy path and errors."""

    def test_creates_session(
        self, service: RecordingService, session_repo: MagicMock
    ) -> None:
        """A RecordingSession is created and saved with RECORDING status."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            session_id = service.start_recording("t1", "https://example.com/stream.m3u8")

        session_repo.save.assert_called_once()
        saved = session_repo.save.call_args[0][0]
        assert saved.id == session_id
        assert saved.stream_target_id == "t1"
        assert saved.status.value == "recording"
        assert saved.source_platform == Platform.TWITCH
        assert saved.started_at == NOW
        assert saved.ended_at is None

    def test_starts_ffmpeg_runner(
        self, service: RecordingService, runner: MagicMock, file_manager: MagicMock
    ) -> None:
        """The FFmpegRunner is called with the stream URL, allocated path,
        and headers=None (no cookie service configured)."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "https://example.com/stream.m3u8")

        runner.start_recording.assert_called_once()
        args, kwargs = runner.start_recording.call_args
        assert kwargs["stream_url"] == "https://example.com/stream.m3u8"
        assert kwargs["output_path"] == str(file_manager.allocate_path.return_value)
        assert kwargs["headers"] is None
        assert kwargs["on_exit"] is not None

    def test_creates_raw_ts_artifact(
        self, service: RecordingService, artifact_repo: MagicMock
    ) -> None:
        """A RAW_TS artifact with WRITING status is created."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "https://example.com/stream.m3u8")

        artifact_repo.save.assert_called_once()
        saved = artifact_repo.save.call_args[0][0]
        assert saved.artifact_type == ArtifactType.RAW_TS
        assert saved.container_format == ContainerFormat.TS
        assert saved.status.value == "writing"

    def test_emits_events(
        self, service: RecordingService, event_bus: MagicMock
    ) -> None:
        """RecordingStarted and LiveDetected events are emitted."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "https://example.com/stream.m3u8")

        assert event_bus.publish.call_count >= 2
        topics = [call[0][0] for call in event_bus.publish.call_args_list]
        assert "recording.started" in topics
        assert "live.detected" in topics

    def test_raises_on_missing_target(
        self, service: RecordingService, target_repo: MagicMock
    ) -> None:
        """ValueError is raised when the stream target does not exist."""
        target_repo.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            service.start_recording("nonexistent", "url")

    def test_tracks_session_to_recording_mapping(
        self, service: RecordingService
    ) -> None:
        """The session_id is mapped to the runner recording_id internally."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            session_id = service.start_recording("t1", "url")

        assert service._session_to_recording[session_id] == "runner-recording-id-123"

    # ── Cookie / header pass-through ──────────────────────────────

    def test_passes_cookie_header_when_service_provides_cookies(
        self,
        service_with_cookies: RecordingService,
        runner: MagicMock,
        cookie_service: MagicMock,
    ) -> None:
        """When CookieService returns a cookie string, it is passed as
        an HTTP header to the FFmpegRunner."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service_with_cookies.start_recording("t1", "https://example.com/stream.m3u8")

        runner.start_recording.assert_called_once()
        _call_kwargs = runner.start_recording.call_args.kwargs
        assert _call_kwargs.get("headers") == {"Cookie": "sessionid=abc123; csrftoken=xyz"}

    def test_queries_cookie_by_platform(
        self,
        service_with_cookies: RecordingService,
        cookie_service: MagicMock,
        target_repo: MagicMock,
    ) -> None:
        """The cookie service is queried using the target's platform value."""
        target_repo.get.return_value = _target(platform=Platform.TIKTOK)

        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service_with_cookies.start_recording("t1", "https://example.com/stream.m3u8")

        cookie_service.get_cookie_string.assert_called_once_with("tiktok")

    def test_passes_no_header_when_cookie_service_returns_empty(
        self,
        service_with_cookies: RecordingService,
        runner: MagicMock,
        cookie_service: MagicMock,
    ) -> None:
        """When CookieService returns an empty string, headers is None
        (no -headers flag added to ffmpeg)."""
        cookie_service.get_cookie_string.return_value = ""

        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service_with_cookies.start_recording("t1", "https://example.com/stream.m3u8")

        runner.start_recording.assert_called_once()
        _call_kwargs = runner.start_recording.call_args.kwargs
        assert _call_kwargs.get("headers") is None

    def test_passes_no_header_when_no_cookie_service(
        self, service: RecordingService, runner: MagicMock
    ) -> None:
        """When no CookieService is configured, headers is None."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "https://example.com/stream.m3u8")

        runner.start_recording.assert_called_once()
        _call_kwargs = runner.start_recording.call_args.kwargs
        assert _call_kwargs.get("headers") is None

    # ── Recording config passthrough ─────────────────────────────

    def test_passes_per_stream_directory_from_config(
        self,
        service_with_config: RecordingService,
        file_manager: MagicMock,
    ) -> None:
        """The resolved per_stream_directory value is passed to FileManager."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service_with_config.start_recording("t1", "https://example.com/stream.m3u8")

        file_manager.allocate_path.assert_called_once()
        kwargs = file_manager.allocate_path.call_args.kwargs
        assert kwargs.get("per_stream_directory") is False

    def test_default_config(
        self, service: RecordingService, file_manager: MagicMock
    ) -> None:
        """When no config is given, internal defaults are used."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "https://example.com/stream.m3u8")

        file_manager.allocate_path.assert_called_once()
        kwargs = file_manager.allocate_path.call_args.kwargs
        # Internal default for per_stream_directory is False
        assert kwargs.get("per_stream_directory") is False


# ======================================================================
# Stop Recording
# ======================================================================


class TestStopRecording:
    """RecordingService.stop_recording — teardown and finalisation."""

    def test_stops_runner(
        self,
        service: RecordingService,
        runner: MagicMock,
        session_repo: MagicMock,
    ) -> None:
        """The runner's stop_recording is called with the correct id."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            session_id = service.start_recording("t1", "url")

        # Make session look active in the repo
        session = session_repo.save.call_args[0][0]
        session_repo.get.return_value = session

        service.stop_recording(session_id)

        runner.stop_recording.assert_called_once_with("runner-recording-id-123")

    def test_completes_session(
        self,
        service: RecordingService,
        session_repo: MagicMock,
    ) -> None:
        """The session is marked as completed after stopping."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            session_id = service.start_recording("t1", "url")

        session = session_repo.save.call_args[0][0]
        session_repo.get.return_value = session

        with patch("app.application.services.recording_service.utc_now") as mock_now:
            mock_now.return_value = NOW
            service.stop_recording(session_id)

        # The session should be saved with COMPLETED status
        saved_again = session_repo.save.call_args[0][0]
        assert saved_again.status.value == "completed"
        assert saved_again.ended_at is not None

    def test_emits_recording_finished(
        self,
        service: RecordingService,
        session_repo: MagicMock,
        event_bus: MagicMock,
    ) -> None:
        """RecordingFinished event is emitted after stopping."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            session_id = service.start_recording("t1", "url")

        session = session_repo.save.call_args[0][0]
        session_repo.get.return_value = session

        service.stop_recording(session_id)

        finished_events = [
            call for call in event_bus.publish.call_args_list
            if call[0][0] == "recording.finished"
        ]
        assert len(finished_events) >= 1

    def test_stop_unknown_session(
        self, service: RecordingService, session_repo: MagicMock
    ) -> None:
        """Stopping a nonexistent session is logged but does not raise."""
        session_repo.get.return_value = None
        service.stop_recording("unknown-session")  # should not raise

    def test_stop_inactive_session(
        self, service: RecordingService, session_repo: MagicMock
    ) -> None:
        """Stopping a completed session is a no-op."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        session = MagicMock(spec=RecordingSession)
        session.is_active = False
        session.status = RecordingStatus.COMPLETED
        session_repo.get.return_value = session

        service.stop_recording("completed-session")  # should not raise

    def test_creates_final_mp4_artifact_when_file_exists(
        self,
        service: RecordingService,
        session_repo: MagicMock,
        artifact_repo: MagicMock,
        runner: MagicMock,
    ) -> None:
        """When the .mp4 exists after transmux, a FINAL_MP4 artifact is created."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            session_id = service.start_recording("t1", "url")

        session = session_repo.save.call_args[0][0]
        session_repo.get.return_value = session

        # Return the RAW_TS artifact on list_by_session
        from app.domain.recording.artifacts import RecordingArtifact
        from app.domain.shared.types import ArtifactStatus

        ts_artifact = RecordingArtifact(
            id="art-1",
            recording_session_id=session_id,
            artifact_type=ArtifactType.RAW_TS,
            path="/data/recordings/streamer/20260522_abcd.ts",
            container_format=ContainerFormat.TS,
            status=ArtifactStatus.WRITING,
            size_bytes=None,
            duration_seconds=None,
            checksum=None,
            created_at=NOW,
            updated_at=NOW,
        )
        artifact_repo.list_by_session.return_value = [ts_artifact]

        with (
            patch("app.application.services.recording_service.Path.is_file") as mock_isfile,
            patch("app.application.services.recording_service.Path.stat") as mock_stat,
        ):
            mock_isfile.return_value = True
            mock_stat.return_value.st_size = 1_234_567
            service.stop_recording(session_id)

        # Check that a FINAL_MP4 artifact was saved
        final_mp4_saves = [
            call for call in artifact_repo.save.call_args_list
            if call[0][0].artifact_type == ArtifactType.FINAL_MP4
        ]
        assert len(final_mp4_saves) >= 1
        assert final_mp4_saves[0][0][0].path == "/data/recordings/streamer/20260522_abcd.mp4"


class TestStopAll:
    """RecordingService.stop_all — batch stop."""

    def test_stops_runner_and_clears_mapping(
        self, service: RecordingService, runner: MagicMock
    ) -> None:
        """stop_all calls runner.stop_all and clears the session mapping."""
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "url")

        service.stop_all()

        runner.stop_all.assert_called_once()
        assert len(service._session_to_recording) == 0


class TestFinalizeAllActiveSessions:
    """RecordingService.finalize_all_active_sessions — safety net."""

    def test_finalizes_orphaned_sessions(
        self, service: RecordingService, session_repo: MagicMock
    ) -> None:
        """Sessions still RECORDING in the DB are aborted."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        active = RecordingSession(
            id="orphan-1",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=1),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
        completed = RecordingSession(
            id="done-1",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=2),
            ended_at=NOW - timedelta(hours=1, minutes=30),
            status=RecordingStatus.COMPLETED,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=1, minutes=30),
        )
        session_repo.list_all.return_value = [active, completed]

        count = service.finalize_all_active_sessions(reason="test_shutdown")

        assert count == 1
        # The active session should have been saved with ABORTED status
        save_calls = [
            call for call in session_repo.save.call_args_list
            if call[0][0].id == "orphan-1"
        ]
        assert len(save_calls) >= 1
        saved = save_calls[-1][0][0]
        assert saved.status == RecordingStatus.ABORTED
        assert saved.split_reason == "test_shutdown"
        assert saved.ended_at is not None

    def test_no_active_sessions_returns_zero(
        self, service: RecordingService, session_repo: MagicMock
    ) -> None:
        """When all sessions are already terminal, returns 0."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        finished = RecordingSession(
            id="done-1",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=2),
            ended_at=NOW - timedelta(hours=1),
            status=RecordingStatus.COMPLETED,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=1),
        )
        session_repo.list_all.return_value = [finished]

        count = service.finalize_all_active_sessions()
        assert count == 0

    def test_stop_all_finalizes_sessions(
        self, service: RecordingService, session_repo: MagicMock, runner: MagicMock
    ) -> None:
        """stop_all calls finalize_all_active_sessions internally."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        orphan = RecordingSession(
            id="orphan-2",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=1),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
        session_repo.list_all.return_value = [orphan]

        # start a recording so there's a runner mapping too
        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service.start_recording("t1", "url")

        service.stop_all()

        runner.stop_all.assert_called_once()
        assert len(service._session_to_recording) == 0
        # orphan should have gone through finalize_all_active_sessions
        assert session_repo.save.called


class TestOnRunnerExit:
    """RecordingService._on_runner_exit — unexpected ffmpeg exit."""

    def test_finalizes_session_on_unexpected_exit(
        self, service: RecordingService, session_repo: MagicMock, artifact_repo: MagicMock,
    ) -> None:
        """When ffmpeg exits unexpectedly, the session is marked as FAILED."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus, ArtifactStatus, ArtifactType
        from app.domain.recording.artifacts import RecordingArtifact

        session = RecordingSession(
            id="session-exit-1",
            stream_target_id="t1",
            started_at=NOW - timedelta(minutes=10),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(minutes=10),
            updated_at=NOW - timedelta(minutes=10),
        )
        session_repo.get.return_value = session
        artifact_repo.list_by_session.return_value = []

        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service._on_runner_exit("session-exit-1", "runner-recording-id-xxx")

        assert session.status == RecordingStatus.FAILED
        assert session.error_code == "FFMPEG_EXIT"
        assert session.ended_at is not None
        # Should save at least once with FAILED status
        save_calls = [
            call for call in session_repo.save.call_args_list
            if call[0][0].id == "session-exit-1"
        ]
        assert len(save_calls) >= 1
        saved = save_calls[-1][0][0]
        assert saved.status == RecordingStatus.FAILED

    def test_runner_exit_already_finalized_is_noop(
        self, service: RecordingService, session_repo: MagicMock,
    ) -> None:
        """If the session is already finished, on_runner_exit is a no-op."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus

        session = RecordingSession(
            id="session-done",
            stream_target_id="t1",
            started_at=NOW - timedelta(hours=2),
            ended_at=NOW - timedelta(hours=1),
            status=RecordingStatus.COMPLETED,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(hours=2),
            updated_at=NOW - timedelta(hours=1),
        )
        session_repo.get.return_value = session

        service._on_runner_exit("session-done", "runner-id")

        # Should not call save for a completed session
        completed_saves = [
            call for call in session_repo.save.call_args_list
            if call[0][0].id == "session-done"
        ]
        assert len(completed_saves) == 0

    def test_runner_exit_unknown_session(
        self, service: RecordingService, session_repo: MagicMock,
    ) -> None:
        """If the session doesn't exist in DB, on_runner_exit is a no-op."""
        session_repo.get.return_value = None
        # Should not raise
        service._on_runner_exit("nonexistent", "runner-id")

    def test_runner_exit_updates_artifact(
        self, service: RecordingService, session_repo: MagicMock,
        artifact_repo: MagicMock,
    ) -> None:
        """The RAW_TS artifact is marked READY on unexpected exit."""
        from app.domain.recording.session import RecordingSession
        from app.domain.shared.types import RecordingStatus, ArtifactStatus, ArtifactType
        from app.domain.recording.artifacts import RecordingArtifact

        session = RecordingSession(
            id="session-exit-2",
            stream_target_id="t1",
            started_at=NOW - timedelta(minutes=10),
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=Platform.TWITCH,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=NOW - timedelta(minutes=10),
            updated_at=NOW - timedelta(minutes=10),
        )
        session_repo.get.return_value = session

        ts_artifact = RecordingArtifact(
            id="art-exit-1",
            recording_session_id="session-exit-2",
            artifact_type=ArtifactType.RAW_TS,
            path="/data/recordings/streamer/exit_test.ts",
            container_format=ContainerFormat.TS,
            status=ArtifactStatus.WRITING,
            size_bytes=1_000_000,
            duration_seconds=None,
            checksum=None,
            created_at=NOW - timedelta(minutes=10),
            updated_at=NOW - timedelta(minutes=10),
        )
        artifact_repo.list_by_session.return_value = [ts_artifact]

        with patch("app.application.services.recording_service.utc_now", return_value=NOW):
            service._on_runner_exit("session-exit-2", "runner-id")

        # The artifact should be saved with READY status
        artifact_saves = [
            call for call in artifact_repo.save.call_args_list
            if call[0][0].id == "art-exit-1"
        ]
        assert len(artifact_saves) >= 1
        saved_artifact = artifact_saves[-1][0][0]
        assert saved_artifact.status == ArtifactStatus.READY
        assert saved_artifact.updated_at == NOW
