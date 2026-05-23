"""RecordingService — orchestrates ffmpeg recording with session lifecycle.

Coordinates detection events from the :class:`MonitoringCycle` with the
:class:`FFmpegRunner`, persists :class:`RecordingSession` and
:class:`RecordingArtifact` entities, and emits domain events via the
:class:`EventBus`.

Flow
----
**Start**::

    MonitoringCycle detects false → true is_live
        → RecordingService.start_recording(target_id, stream_url)
            → creates RecordingSession (status=RECORDING)
            → allocates .ts path via FileManager
            → starts FFmpegRunner
            → creates RecordingArtifact (status=WRITING, RAW_TS)
            → saves session & artifact
            → emits RecordingStarted event

**Stop**::

    MonitoringCycle detects true → false is_live
        → RecordingService.stop_recording(session_id)
            → stops FFmpegRunner (→ sends 'q' → waits → transmuxes to .mp4)
            → updates RAW_TS artifact (READY)
            → creates FINAL_MP4 artifact
            → closes RecordingSession (COMPLETED)
            → emits RecordingFinished event
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.domain.events.events import (
    LiveDetected,
    RecordingFinished,
    RecordingProgress,
    RecordingStarted,
)
from app.domain.recording.artifacts import RecordingArtifact
from app.domain.recording.config import RecordingConfig, resolve_recording_config
from app.domain.recording.session import RecordingSession
from app.domain.shared.types import (
    ArtifactStatus,
    ArtifactType,
    ContainerFormat,
    Platform,
    RecordingStatus,
    utc_now,
)
from app.domain.stream_target.entities import StreamTarget
from app.application.services.cookie_service import CookieService
from app.infrastructure.events.event_bus import EventBus
from app.infrastructure.ffmpeg.process_runner import FFmpegRunner
from app.infrastructure.files.file_manager import FileManager
from app.infrastructure.repositories.recording_artifact_repository import (
    RecordingArtifactRepository,
)
from app.infrastructure.repositories.recording_session_repository import (
    RecordingSessionRepository,
)
from app.infrastructure.repositories.stream_target_repository import (
    StreamTargetRepository,
)

logger = __import__("logging").getLogger(__name__)


class RecordingService:
    """Orchestrates recording sessions from detection through finalisation.

    Parameters
    ----------
    runner:
        The ffmpeg subprocess manager.
    file_manager:
        File path allocator for recording artifacts.
    session_repo:
        Repository for ``RecordingSession`` entities.
    artifact_repo:
        Repository for ``RecordingArtifact`` entities.
    target_repo:
        Repository for ``StreamTarget`` entities.
    event_bus:
        Optional event bus for emitting domain events.
    cookie_service:
        Optional cookie service for authenticated streams.
    recording_config:
        Global recording behaviour configuration.  Falls back to
        :class:`RecordingConfig` internal defaults when ``None``.
    """

    def __init__(
        self,
        runner: FFmpegRunner,
        file_manager: FileManager,
        session_repo: RecordingSessionRepository,
        artifact_repo: RecordingArtifactRepository,
        target_repo: StreamTargetRepository,
        event_bus: EventBus | None = None,
        cookie_service: CookieService | None = None,
        recording_config: RecordingConfig | None = None,
    ) -> None:
        self._runner = runner
        self._file_manager = file_manager
        self._session_repo = session_repo
        self._artifact_repo = artifact_repo
        self._target_repo = target_repo
        self._event_bus = event_bus
        self._cookie_service = cookie_service
        self._recording_config = recording_config or RecordingConfig()

        # Maps session_id → runner recording_id for targeted stop.
        self._session_to_recording: dict[str, str] = {}

    # ── Public API ──────────────────────────────────────────────────

    def start_recording(self, stream_target_id: str, stream_url: str) -> str:
        """Begin recording a live stream.

        Creates a :class:`RecordingSession`, allocates a ``.ts`` output
        path, spawns ffmpeg, creates a :class:`RecordingArtifact`, and
        emits a :class:`RecordingStarted` event.

        Args:
            stream_target_id: The stream target being recorded.
            stream_url: The resolved stream URL to record from.

        Returns:
            The ``RecordingSession.id`` for the new session.

        Raises:
            ValueError: If *stream_target_id* does not exist.
            RuntimeError: If ffmpeg fails to start.
        """
        target = self._target_repo.get(stream_target_id)
        if target is None:
            raise ValueError(f"Stream target {stream_target_id!r} not found")

        now = utc_now()
        session_id = _new_id()

        # ── Create RecordingSession ───────────────────────────────
        session = RecordingSession(
            id=session_id,
            stream_target_id=stream_target_id,
            started_at=now,
            ended_at=None,
            status=RecordingStatus.RECORDING,
            source_platform=target.platform,
            stream_title=None,
            detected_by_queue=None,
            detection_latency_seconds=None,
            scheduled_hint_delay_minutes=None,
            split_reason=None,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        self._session_repo.save(session)

        # ── Resolve effective recording config ────────────────────
        config = resolve_recording_config(self._recording_config)

        # ── Build optional HTTP headers (cookies) ─────────────────
        headers: dict[str, str] | None = None
        cookie_str = self._cookie_service.get_cookie_string(target.platform.value) if self._cookie_service else ""
        if cookie_str:
            headers = {"Cookie": cookie_str}

        # ── Allocate file path and start ffmpeg ───────────────────
        ts_path = self._file_manager.allocate_path(
            handle=target.handle,
            extension="ts",
            stream_title=None,
            per_stream_directory=config.per_stream_directory,
        )
        runner_recording_id = self._runner.start_recording(
            stream_url=stream_url,
            output_path=str(ts_path),
            headers=headers,
            on_exit=lambda rid: self._on_runner_exit(session_id, rid),
            segment_enabled=config.segment_enabled,
            segment_time_seconds=config.segment_time_seconds,
        )

        # ── Track session → recording mapping ────────────────────
        self._session_to_recording[session_id] = runner_recording_id

        # ── Create RAW_TS artifact ────────────────────────────────
        artifact = RecordingArtifact(
            id=_new_id(),
            recording_session_id=session_id,
            artifact_type=ArtifactType.RAW_TS,
            path=str(ts_path),
            container_format=ContainerFormat.TS,
            status=ArtifactStatus.WRITING,
            size_bytes=None,
            duration_seconds=None,
            checksum=None,
            created_at=now,
            updated_at=now,
        )
        self._artifact_repo.save(artifact)

        # ── Emit event ────────────────────────────────────────────
        self._emit(
            "recording.started",
            RecordingStarted(
                stream_target_id=stream_target_id,
                recording_session_id=session_id,
                artifact_path=str(ts_path),
            ),
        )
        self._emit(
            "live.detected",
            LiveDetected(
                stream_target_id=stream_target_id,
                recording_session_id=session_id,
            ),
        )

        logger.info(
            "Recording started: session=%s target=%s url=%s",
            session_id[:8],
            stream_target_id,
            stream_url,
        )
        return session_id

    def stop_recording(self, recording_session_id: str) -> None:
        """Stop an active recording and finalize its session.

        Stops ffmpeg (which triggers transmux to ``.mp4``), marks the
        RAW_TS artifact as ready, creates a FINAL_MP4 artifact, closes
        the :class:`RecordingSession`, clears the snapshot's recording
        state, and emits a :class:`RecordingFinished` event.

        Args:
            recording_session_id: The session to stop.
        """
        session = self._session_repo.get(recording_session_id)
        if session is None:
            logger.warning(
                "Cannot stop: session %s not found", recording_session_id[:8]
            )
            return
        if not session.is_active:
            logger.warning(
                "Session %s is not active (status=%s)",
                recording_session_id[:8],
                session.status.value,
            )
            return

        # ── Stop ffmpeg via the recorded mapping ──────────────────
        runner_id = self._session_to_recording.pop(recording_session_id, None)
        if runner_id is not None:
            self._runner.stop_recording(runner_id)
        else:
            # Fallback: no mapping found (e.g. after restart) — stop all.
            logger.warning(
                "No runner mapping for session %s — stopping all recordings",
                recording_session_id[:8],
            )
            self._runner.stop_all()

        # ── Look up artifacts for this session ────────────────────
        artifacts = self._artifact_repo.list_by_session(recording_session_id)
        ts_artifact = next(
            (a for a in artifacts if a.artifact_type == ArtifactType.RAW_TS),
            None,
        )

        # ── Update the RAW_TS artifact ────────────────────────────
        now = utc_now()
        if ts_artifact is not None:
            mp4_path = str(ts_artifact.path).rsplit(".", 1)[0] + ".mp4"
            self._artifact_repo.save(
                RecordingArtifact(
                    id=ts_artifact.id,
                    recording_session_id=ts_artifact.recording_session_id,
                    artifact_type=ts_artifact.artifact_type,
                    path=ts_artifact.path,
                    container_format=ts_artifact.container_format,
                    status=ArtifactStatus.READY,
                    size_bytes=ts_artifact.size_bytes,
                    duration_seconds=ts_artifact.duration_seconds,
                    checksum=ts_artifact.checksum,
                    created_at=ts_artifact.created_at,
                    updated_at=now,
                )
            )

            # ── Create FINAL_MP4 artifact if the mp4 exists ───────
            mp4_path_obj = Path(mp4_path)
            if mp4_path_obj.is_file():
                mp4_artifact = RecordingArtifact(
                    id=_new_id(),
                    recording_session_id=recording_session_id,
                    artifact_type=ArtifactType.FINAL_MP4,
                    path=mp4_path,
                    container_format=ContainerFormat.MP4,
                    status=ArtifactStatus.READY,
                    size_bytes=mp4_path_obj.stat().st_size,
                    duration_seconds=session.duration_seconds,
                    checksum=None,
                    created_at=now,
                    updated_at=now,
                )
                self._artifact_repo.save(mp4_artifact)

        # ── Close the session ─────────────────────────────────────
        try:
            session.complete(ended_at=now)
            self._session_repo.save(session)
        except ValueError as exc:
            logger.error("Failed to complete session %s: %s", session.id[:8], exc)

        # ── Emit event ────────────────────────────────────────────
        self._emit(
            "recording.finished",
            RecordingFinished(
                recording_session_id=recording_session_id,
                status=RecordingStatus.COMPLETED.value,
            ),
        )

        logger.info(
            "Recording finished: session=%s target=%s duration=%s",
            recording_session_id[:8],
            session.stream_target_id,
            session.duration_seconds,
        )

    def stop_all(self) -> None:
        """Stop every active recording and finalise all sessions.

        Stops all ffmpeg processes via the runner, then finalises
        every active session in the database as ``ABORTED`` so no
        orphaned ``RECORDING`` sessions survive a restart.
        """
        self._runner.stop_all()
        self._session_to_recording.clear()
        self.finalize_all_active_sessions(reason="shutdown")

    def finalize_all_active_sessions(self, reason: str = "shutdown") -> int:
        """Finalise every active (still ``RECORDING``) session in the DB.

        This is a safety net for sessions that were never properly
        closed — e.g. after a crash where ``_on_runner_exit`` was not
        called, or during shutdown when the runner mapping is already
        gone.

        Args:
            reason:  Reason label stored as ``split_reason``.

        Returns:
            The number of sessions finalised.
        """
        count = 0
        now = utc_now()
        for session in self._session_repo.list_all():
            if not session.is_active:
                continue
            try:
                session.abort(reason=reason)
                session.ended_at = now
                session.updated_at = now
                self._session_repo.save(session)
                count += 1
                logger.info(
                    "Finalised orphaned session %s (target=%s, reason=%s)",
                    session.id[:8], session.stream_target_id, reason,
                )
            except ValueError as exc:
                logger.error(
                    "Could not finalise session %s: %s",
                    session.id[:8], exc,
                )
        if count:
            logger.info("Finalised %d orphaned recording session(s)", count)
        return count

    # ── Runner callback ───────────────────────────────────────────────

    def _on_runner_exit(self, session_id: str, runner_recording_id: str) -> None:
        """Callback invoked when ffmpeg exits unexpectedly.

        Looks up the session, finalises it as ``FAILED`` or ``ABORTED``
        depending on context, and cleans up the in-memory mapping.
        This prevents orphaned ``RECORDING`` sessions when ffmpeg
        crashes, the stream ends, or the process is killed externally.
        """
        session = self._session_repo.get(session_id)
        if session is None:
            logger.warning(
                "Runner exit callback: session %s not found",
                session_id[:8],
            )
            return

        if not session.is_active:
            logger.debug(
                "Runner exit callback: session %s already finalised",
                session_id[:8],
            )
            return

        self._session_to_recording.pop(session_id, None)

        now = utc_now()

        # ── Update RAW_TS artifact to READY ──────────────────────
        artifacts = self._artifact_repo.list_by_session(session_id)
        ts_artifact = next(
            (a for a in artifacts if a.artifact_type == ArtifactType.RAW_TS),
            None,
        )
        if ts_artifact is not None and ts_artifact.status == ArtifactStatus.WRITING:
            self._artifact_repo.save(
                RecordingArtifact(
                    id=ts_artifact.id,
                    recording_session_id=ts_artifact.recording_session_id,
                    artifact_type=ts_artifact.artifact_type,
                    path=ts_artifact.path,
                    container_format=ts_artifact.container_format,
                    status=ArtifactStatus.READY,
                    size_bytes=ts_artifact.size_bytes,
                    duration_seconds=ts_artifact.duration_seconds,
                    checksum=ts_artifact.checksum,
                    created_at=ts_artifact.created_at,
                    updated_at=now,
                )
            )

        # ── Finalise the session ─────────────────────────────────
        try:
            session.fail(
                error_code="FFMPEG_EXIT",
                error_message="ffmpeg process exited unexpectedly",
            )
            session.ended_at = now
            session.updated_at = now
            self._session_repo.save(session)
        except ValueError as exc:
            # If fail() transition is invalid, try abort()
            try:
                session.abort(reason="unexpected_ffmpeg_exit")
                session.ended_at = now
                session.updated_at = now
                self._session_repo.save(session)
            except ValueError:
                logger.error(
                    "Could not finalise session %s after runner exit: %s",
                    session_id[:8], exc,
                )
                return

        self._emit(
            "recording.finished",
            RecordingFinished(
                recording_session_id=session_id,
                status=RecordingStatus.FAILED.value,
            ),
        )

        logger.info(
            "Session %s finalised after unexpected ffmpeg exit "
            "(target=%s, duration=%s)",
            session_id[:8],
            session.stream_target_id,
            session.duration_seconds,
        )

    # ── Event emission ────────────────────────────────────────────

    def _emit(self, topic: str, event: Any) -> None:
        """Publish a domain event if an event bus is configured."""
        if self._event_bus is not None:
            self._event_bus.publish(topic, _event_to_dict(event))


# ── Module-level helpers ───────────────────────────────────────────────


def _new_id() -> str:
    return uuid.uuid4().hex


def _event_to_dict(event: Any) -> dict:
    """Convert a dataclass event to a plain dict for the EventBus."""
    if hasattr(event, "__dataclass_fields__"):
        return {
            f.name: _serialise(getattr(event, f.name))
            for f in event.__dataclass_fields__.values()
        }
    return {"value": str(event)}


def _serialise(value: Any) -> Any:
    """Convert datetime to ISO string for JSON-safe payloads."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
