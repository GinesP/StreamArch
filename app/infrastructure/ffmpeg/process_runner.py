"""FFmpegRunner — manages ffmpeg subprocess lifecycle for recordings.

Each call to :meth:`FFmpegRunner.start_recording` spawns an ffmpeg
process in a background thread.  Callers refer to the process by a
unique *recording_id* string.

Recording is done to ``.ts`` container first (tolerant to crashes).
On stop, the ``.ts`` is optionally transmuxed to ``.mp4`` by the
:mod:`app.infrastructure.ffmpeg.transmuxer` module.

Progress data is extracted from ffmpeg's stderr output by the
:mod:`app.infrastructure.ffmpeg.progress_parser` module.

Command-line flags
------------------
The assembled ffmpeg command mirrors the proven base profile from
StreamCapQT's ``app/core/media/ffmpeg_builders/base.py``::

    ffmpeg -y                                       # overwrite
           -hide_banner                             # suppress banner
           [-headers "Name: Value" ...]              # optional cookies
           -protocol_whitelist <list>                # security hardening
           -rw_timeout 10000000                      # 10 s network timeout
           -user_agent <fixed mobile UA>             # mobile Chrome UA
           -thread_queue_size 1024                   # avoid queue overflow
           -analyzeduration 20000000                 # faster startup
           -probesize 10000000                       # faster startup
           -fflags +discardcorrupt+igndts            # handle corrupt packets
           -reconnect 1                              # reconnect on broken pipe
           -reconnect_at_eof 1
           -reconnect_streamed 1
           -reconnect_delay_max 5                    # max 5 s between retries
           -i <stream_url>                           # input
           -sn                                       # no subtitles
           -dn                                       # no data streams
           -max_muxing_queue_size 1024               # prevent mux overflow
           -correct_ts_overflow 1                    # timestamp correction
           -avoid_negative_ts 1                      # shift timestamps
           -flush_packets 1                          # low-latency flush
           -map 0                                    # all input streams
           -c:v copy                                 # no video re-encode
           -c:a copy                                 # no audio re-encode
           -f mpegts                                 # TS container
           <output_path>

Flags deliberately excluded from StreamCapQT's base:
* ``-v verbose``   — would flood stderr and interfere with progress parsing.
* ``-loglevel error`` — would suppress progress output needed by the
  :mod:`~app.infrastructure.ffmpeg.progress_parser` module.
* ``-bufsize``     — only meaningful when encoding; no effect with ``-c copy``.
* ``-re``          — input rate-control flag; irrelevant for live HLS sources.
"""

import logging
import os
import subprocess
import threading
import uuid
from collections import deque
from typing import Any

from app.infrastructure.ffmpeg.progress_parser import FFmpegProgress, parse_progress_line
from app.infrastructure.ffmpeg.shutdown import stop_ffmpeg_gracefully
from app.infrastructure.ffmpeg.transmuxer import transmux_to_mp4

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

_STDERR_MAX_LINES: int = 500
"""Maximum stderr lines kept in the ring buffer per recording."""

_DEFAULT_STOP_TIMEOUT: int = 10
"""Default timeout (seconds) for graceful ffmpeg stop."""

_USER_AGENT: str = (
    "Mozilla/5.0 (Linux; Android 14; K) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.6723.58 Mobile Safari/537.36"
)
"""Fixed mobile User-Agent matching StreamCapQT's profile (Android Chrome)."""

_PROTOCOL_WHITELIST: str = (
    "crypto,file,http,https,tcp,tls,udp,rtp,rtmp,httpproxy"
)
"""Allowed network protocols for ffmpeg (StreamCapQT base profile)."""


# ── Internal bookkeeping ───────────────────────────────────────────────


class _RecordingProcessInfo:
    """Tracking info for a single active ffmpeg recording process."""

    def __init__(
        self,
        recording_id: str,
        process: subprocess.Popen,
        output_path: str,
        stream_url: str,
    ) -> None:
        self.recording_id = recording_id
        self.process = process
        self.output_path = output_path
        self.stream_url = stream_url

        # Stderr ring buffer (thread-safe via deque)
        self._stderr_buffer: deque[str] = deque(maxlen=_STDERR_MAX_LINES)
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None

    # ── Stderr reader ──────────────────────────────────────────────

    def start_reader(self) -> None:
        """Start a daemon thread that reads stderr into a ring buffer."""
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(
            target=self._read_stderr,
            name=f"ffmpeg-stderr-{self.recording_id[:8]}",
            daemon=True,
        )
        self._reader_thread.start()

    def stop_reader(self) -> None:
        """Signal the reader thread to stop and wait for it."""
        self._reader_stop.set()
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

    @property
    def stderr_lines(self) -> list[str]:
        """Return a snapshot of the current stderr buffer."""
        return list(self._stderr_buffer)

    def _read_stderr(self) -> None:
        """Read lines from ``process.stderr`` into the ring buffer.

        Runs in a daemon thread.  Stops when ``_reader_stop`` is set or
        the pipe is exhausted (process exited and all output consumed).
        """
        try:
            for raw_line in self.process.stderr:  # type: ignore[union-attr]
                if self._reader_stop.is_set():
                    break
                decoded = raw_line.decode("utf-8", errors="replace").rstrip()
                self._stderr_buffer.append(decoded)
        except (OSError, ValueError):
            pass  # Pipe closed or process terminated


# ── Public API ─────────────────────────────────────────────────────────


class FFmpegRunner:
    """Spawns, tracks, and terminates ffmpeg recording processes.

    Thread-safe: :meth:`start_recording`, :meth:`stop_recording`,
    :meth:`get_progress`, and :meth:`is_recording` can be called from
    any thread concurrently.
    """

    def __init__(self) -> None:
        self._recordings: dict[str, _RecordingProcessInfo] = {}
        self._lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────

    def start_recording(
        self,
        stream_url: str,
        output_path: str,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Start recording *stream_url* to *output_path*.

        The recording captures the stream into a ``.ts`` container
        (tolerant to crashes) without re-encoding.

        The ffmpeg command mirrors StreamCapQT's proven base profile
        (see module docstring for the full flag listing).

        Args:
            stream_url: The resolved stream URL to record (m3u8 or
                        direct media URL).
            output_path: Full local path for the output ``.ts`` file.
            headers: Optional HTTP headers to pass to ffmpeg (e.g.
                     ``{"Cookie": "..."}`` for platforms that require
                     authentication).

        Returns:
            A unique recording ID string.  Pass this to
            :meth:`stop_recording` or :meth:`get_progress`.

        Raises:
            FileNotFoundError: If ``ffmpeg`` is not on ``PATH``.
            RuntimeError: If the ffmpeg process could not be started.
        """
        recording_id = uuid.uuid4().hex

        # ── Global preamble ─────────────────────────────────────
        cmd: list[str] = [
            "ffmpeg",
            "-y",                           # Overwrite output
            "-hide_banner",                 # Suppress copyright banner
        ]

        # ── Optional HTTP headers (before -i) ───────────────────
        if headers:
            for name, value in headers.items():
                cmd.extend(["-headers", f"{name}: {value}"])

        # ── Input/network flags (StreamCapQT base profile) ──────
        cmd.extend([
            "-protocol_whitelist", _PROTOCOL_WHITELIST,
            "-rw_timeout", "10000000",      # 10 s read/write timeout
            "-user_agent", _USER_AGENT,     # Fixed mobile UA
            "-thread_queue_size", "1024",   # Prevent queue overflow
            "-analyzeduration", "20000000", # 20 M — faster startup
            "-probesize", "10000000",       # 10 M — faster startup
            "-fflags", "+discardcorrupt+igndts",
            "-reconnect", "1",              # Reconnect on broken pipe
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",    # Max 5 s between retries
        ])

        # ── Input ───────────────────────────────────────────────
        cmd.extend(["-i", stream_url])

        # ── Output flags (StreamCapQT base profile) ─────────────
        cmd.extend([
            "-sn",                          # No subtitles
            "-dn",                          # No data streams
            "-max_muxing_queue_size", "1024",  # Prevent mux overflow
            "-correct_ts_overflow", "1",    # Timestamp correction
            "-avoid_negative_ts", "1",      # Shift timestamps
            "-flush_packets", "1",          # Low-latency flush
            "-map", "0",                    # All input streams
            "-c:v", "copy",                 # No video re-encode
            "-c:a", "copy",                 # No audio re-encode
            "-f", "mpegts",                 # Force TS container
            output_path,
        ])

        logger.info(
            "Starting recording %s: %s -> %s",
            recording_id[:8],
            stream_url,
            output_path,
        )

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("ffmpeg executable not found on PATH")
            raise
        except OSError as exc:
            logger.error("Failed to start ffmpeg: %s", exc)
            raise RuntimeError(f"Failed to start ffmpeg: {exc}") from exc

        info = _RecordingProcessInfo(
            recording_id=recording_id,
            process=process,
            output_path=output_path,
            stream_url=stream_url,
        )
        info.start_reader()

        with self._lock:
            self._recordings[recording_id] = info

        return recording_id

    def stop_recording(
        self,
        recording_id: str,
        timeout: int = _DEFAULT_STOP_TIMEOUT,
        transmux: bool = True,
    ) -> None:
        """Stop an active recording gracefully.

        Sends ``q`` to ffmpeg's stdin, waits for it to exit (up to
        *timeout* seconds), then optionally transmuxes the ``.ts`` to
        ``.mp4`` and deletes the temporary ``.ts``.

        If the recording does not exist or was already stopped, this
        is a no-op (with a debug log message).

        Args:
            recording_id: The ID returned by :meth:`start_recording`.
            timeout: Maximum seconds to wait for ffmpeg to exit.
            transmux: Whether to automatically transmux ``.ts`` to
                      ``.mp4`` after the process finishes.
        """
        info = self._pop_info(recording_id)
        if info is None:
            logger.debug("Recording %s not found (already stopped?)", recording_id[:8])
            return

        self._stop_one(info, timeout=timeout, transmux=transmux)

    # ── Query ──────────────────────────────────────────────────────

    def get_progress(self, recording_id: str) -> FFmpegProgress | None:
        """Return the latest progress data for a recording.

        Scans the stderr ring buffer from newest to oldest and returns
        the first progress line found (i.e. the most recent progress
        snapshot).

        Args:
            recording_id: The ID returned by :meth:`start_recording`.

        Returns:
            An :class:`FFmpegProgress` dict, or ``None`` if no progress
            data is available yet (e.g. ffmpeg just started, or the
            recording is unknown).
        """
        info = self._get_info(recording_id)
        if info is None:
            return None

        for line in reversed(info.stderr_lines):
            progress = parse_progress_line(line)
            if progress is not None:
                return progress
        return None

    def is_recording(self, recording_id: str) -> bool:
        """Check whether a recording is still active.

        Args:
            recording_id: The ID returned by :meth:`start_recording`.

        Returns:
            ``True`` if the recording exists **and** the ffmpeg process
            is still running.
        """
        info = self._get_info(recording_id)
        if info is None:
            return False
        return info.process.poll() is None

    def stop_all(self, timeout: int = _DEFAULT_STOP_TIMEOUT) -> None:
        """Gracefully stop every active recording.

        Args:
            timeout: Maximum seconds per recording to wait for ffmpeg.
        """
        with self._lock:
            ids = list(self._recordings.keys())

        for rid in ids:
            try:
                self.stop_recording(rid, timeout=timeout)
            except Exception:
                logger.exception("Error stopping recording %s", rid[:8])

    # ── Internals ──────────────────────────────────────────────────

    def _get_info(self, recording_id: str) -> _RecordingProcessInfo | None:
        with self._lock:
            return self._recordings.get(recording_id)

    def _pop_info(self, recording_id: str) -> _RecordingProcessInfo | None:
        with self._lock:
            return self._recordings.pop(recording_id, None)

    def _stop_one(
        self,
        info: _RecordingProcessInfo,
        timeout: int = _DEFAULT_STOP_TIMEOUT,
        transmux: bool = True,
    ) -> None:
        """Internal: stop recording, optionally transmux to MP4."""
        rid = info.recording_id[:8]
        process = info.process
        ts_path = info.output_path

        # 1. Gracefully stop the ffmpeg process.
        if process.poll() is None:
            stop_ffmpeg_gracefully(process, timeout_seconds=timeout)

        # 2. Stop the stderr reader thread.
        info.stop_reader()

        # 3. Transmux .ts -> .mp4 if requested.
        if transmux and ts_path and os.path.isfile(ts_path):
            mp4_path = _mp4_path(ts_path)
            success = transmux_to_mp4(ts_path, mp4_path)
            if success:
                _remove_ts(ts_path)
            else:
                logger.warning(
                    "Transmux failed for %s — .ts preserved at %s",
                    rid,
                    ts_path,
                )
        elif transmux:
            logger.warning(
                "Recording %s: .ts file not found at %s, skipping transmux",
                rid,
                ts_path,
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._recordings)


# ── Module-level helpers ───────────────────────────────────────────────


def _mp4_path(ts_path: str) -> str:
    """Derive the .mp4 path by replacing the .ts extension."""
    base, _ = os.path.splitext(ts_path)
    return base + ".mp4"


def _remove_ts(path: str) -> None:
    """Delete a .ts file, logging any errors."""
    try:
        os.remove(path)
        logger.debug("Deleted temporary .ts: %s", path)
    except OSError as exc:
        logger.warning("Could not delete .ts file %s: %s", path, exc)
