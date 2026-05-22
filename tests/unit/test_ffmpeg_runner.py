"""Tests for FFmpegRunner — subprocess lifecycle, progress, and edge cases.

All tests mock ``subprocess.Popen`` and ``os.path.isfile`` to avoid
depending on ffmpeg being installed.
"""

import os
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.ffmpeg.process_runner import FFmpegRunner


# ── Helpers ─────────────────────────────────────────────────────────────


def _mock_process() -> MagicMock:
    """Return a MagicMock that looks like a running subprocess.Popen.

    The mock starts with ``poll()`` returning ``None`` (still running)
    and provides a fake ``stdin`` stream.

    Note: we do NOT use ``spec=subprocess.Popen`` because in Python 3.14+
    ``unittest.mock`` raises ``InvalidSpecError`` when a mock is passed
    as the spec (and ``subprocess.Popen`` may already be mocked by
    ``@patch`` at fixture time).
    """
    proc = MagicMock()
    proc.poll.return_value = None  # Still running
    proc.pid = 12345
    proc.stdin = MagicMock()
    proc.stdin.closed = False
    # stderr that yields one empty line then stops
    proc.stderr = iter([b""])
    return proc


# ── Tests ───────────────────────────────────────────────────────────────


class TestFFmpegRunnerStart:
    """FFmpegRunner.start_recording — process creation."""

    def test_starts_ffmpeg_with_expected_command(self) -> None:
        """start_recording runs ffmpeg with robust input flags and -c copy."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_process()
            runner = FFmpegRunner()
            rid = runner.start_recording(
                stream_url="https://example.com/stream.m3u8",
                output_path="/data/test.ts",
            )

        assert rid is not None
        assert len(rid) == 32  # uuid4 hex
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd: list[str] = args[0]

        # ── Basic structure ─────────────────────────────────────
        assert cmd[0] == "ffmpeg"
        assert cmd[1] == "-y"
        assert cmd[2] == "-hide_banner"

        # ── Input / network flags (StreamCapQT base) ────────────
        assert "-protocol_whitelist" in cmd
        assert "-rw_timeout" in cmd
        assert "-user_agent" in cmd
        assert "-thread_queue_size" in cmd
        assert "-analyzeduration" in cmd
        assert "-probesize" in cmd
        assert "-fflags" in cmd
        assert "+discardcorrupt+igndts" in cmd
        assert "-reconnect" in cmd
        assert "-reconnect_at_eof" in cmd
        assert "-reconnect_streamed" in cmd
        assert "-reconnect_delay_max" in cmd

        # ── Input ────────────────────────────────────────────────
        i_pos = cmd.index("-i")
        assert cmd[i_pos + 1] == "https://example.com/stream.m3u8"

        # All network / input flags appear before -i
        for flag in ("-protocol_whitelist", "-rw_timeout", "-user_agent",
                      "-thread_queue_size", "-analyzeduration", "-probesize",
                      "-reconnect"):
            assert cmd.index(flag) < i_pos, f"{flag} should be before -i"

        # ── Output flags (StreamCapQT base, after -i) ───────────
        assert "-sn" in cmd
        sn_pos = cmd.index("-sn")
        assert sn_pos > i_pos, "-sn should be after -i"
        assert "-dn" in cmd
        dn_pos = cmd.index("-dn")
        assert dn_pos > i_pos, "-dn should be after -i"

        assert "-max_muxing_queue_size" in cmd
        mux_pos = cmd.index("-max_muxing_queue_size")
        assert cmd[mux_pos + 1] == "1024"
        assert mux_pos > i_pos

        assert "-correct_ts_overflow" in cmd
        ts_pos = cmd.index("-correct_ts_overflow")
        assert cmd[ts_pos + 1] == "1"
        assert ts_pos > i_pos

        assert "-avoid_negative_ts" in cmd
        ant_pos = cmd.index("-avoid_negative_ts")
        assert cmd[ant_pos + 1] == "1"
        assert ant_pos > i_pos

        assert "-flush_packets" in cmd
        flush_pos = cmd.index("-flush_packets")
        assert cmd[flush_pos + 1] == "1"
        assert flush_pos > i_pos

        # ── Map + codec copy ─────────────────────────────────────
        assert "-map" in cmd
        map_pos = cmd.index("-map")
        assert cmd[map_pos + 1] == "0"
        assert cmd[map_pos + 2] == "-c:v"
        assert cmd[map_pos + 3] == "copy"
        assert cmd[map_pos + 4] == "-c:a"
        assert cmd[map_pos + 5] == "copy"
        assert "-f" in cmd
        f_pos = cmd.index("-f")
        assert cmd[f_pos + 1] == "mpegts"
        assert cmd[-1] == "/data/test.ts"

    def test_passes_headers_as_ffmpeg_args(self) -> None:
        """When headers are provided, they appear as -headers name:value args
        before the input robustness flags and -i."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_process()
            runner = FFmpegRunner()
            rid = runner.start_recording(
                stream_url="https://example.com/stream.m3u8",
                output_path="/data/test.ts",
                headers={"Cookie": "sessionid=abc", "Referer": "https://tiktok.com"},
            )

        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd: list[str] = args[0]

        # -headers args should appear after -y -hide_banner, before input flags
        assert cmd[2] == "-hide_banner"
        assert cmd[3] == "-headers"
        assert cmd[4] == "Cookie: sessionid=abc"
        assert cmd[5] == "-headers"
        assert cmd[6] == "Referer: https://tiktok.com"

        # All headers come before any input flag
        i_pos = cmd.index("-i")
        last_header_pos = max(
            i for i, v in enumerate(cmd) if v == "-headers"
        )
        assert last_header_pos < i_pos

        # Both headers should be present
        assert 'Cookie: sessionid=abc' in cmd
        assert 'Referer: https://tiktok.com' in cmd

    def test_no_headers_when_none_provided(self) -> None:
        """Without headers, the command has no -headers args."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_process()
            runner = FFmpegRunner()
            rid = runner.start_recording(
                stream_url="https://example.com/stream.m3u8",
                output_path="/data/test.ts",
                headers=None,
            )

        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd: list[str] = args[0]
        assert "-headers" not in cmd

    def test_returns_unique_ids(self) -> None:
        """Each call returns a different recording id."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_process()
            runner = FFmpegRunner()
            rid1 = runner.start_recording("url1", "/data/1.ts")
            rid2 = runner.start_recording("url2", "/data/2.ts")
        assert rid1 != rid2

    def test_raises_on_ffmpeg_not_found(self) -> None:
        """FileNotFoundError from Popen is propagated."""
        with patch(
            "app.infrastructure.ffmpeg.process_runner.subprocess.Popen",
            side_effect=FileNotFoundError("ffmpeg"),
        ):
            runner = FFmpegRunner()
            with pytest.raises(FileNotFoundError):
                runner.start_recording("url", "/data/test.ts")

    def test_mobile_user_agent(self) -> None:
        """The user-agent is a fixed mobile Android Chrome UA (StreamCapQT)."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = _mock_process()
            runner = FFmpegRunner()
            runner.start_recording("https://example.com/stream.m3u8", "/data/test.ts")

        args, _ = mock_popen.call_args
        cmd: list[str] = args[0]
        ua_pos = cmd.index("-user_agent")
        ua = cmd[ua_pos + 1]

        # Must be a mobile Android UA (not desktop Windows)
        assert "Android" in ua
        assert "Mobile" in ua
        assert "Windows NT" not in ua
        assert "Chrome/" in ua

    def test_raises_on_popen_error(self) -> None:
        """OSError from Popen is wrapped in RuntimeError."""
        with patch(
            "app.infrastructure.ffmpeg.process_runner.subprocess.Popen",
            side_effect=OSError(8, "Exec format error"),
        ):
            runner = FFmpegRunner()
            with pytest.raises(RuntimeError, match="Failed to start ffmpeg"):
                runner.start_recording("url", "/data/test.ts")


class TestFFmpegRunnerQuery:
    """FFmpegRunner — is_recording and get_progress."""

    def test_is_recording_returns_true_for_active(self) -> None:
        """is_recording returns True while process is alive."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.poll.return_value = None  # still running
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")
        assert runner.is_recording(rid) is True

    def test_is_recording_returns_false_for_unknown(self) -> None:
        """is_recording returns False for an unknown id."""
        runner = FFmpegRunner()
        assert runner.is_recording("nonexistent") is False

    def test_is_recording_returns_false_after_stop(self) -> None:
        """is_recording returns False after stop_recording."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.poll.side_effect = [None, None, 0]  # running x2, then exited
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4") as mock_tmux,
        ):
            mock_isfile.return_value = False  # no .ts file to transmux
            runner.stop_recording(rid)

        assert runner.is_recording(rid) is False

    def test_get_progress_returns_none_for_unknown(self) -> None:
        """get_progress returns None for an unknown recording id."""
        runner = FFmpegRunner()
        assert runner.get_progress("nonexistent") is None

    def test_get_progress_parses_stderr(self) -> None:
        """get_progress reads the stderr buffer and parses it."""
        progress_line = (
            "frame=  123 fps=30.0 q=-1.0 size=    1234KiB "
            "time=00:00:04.10 bitrate=1234.5kbits/s speed=1.00x\n"
        )
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            # stderr yields one progress line
            proc.stderr = iter([progress_line.encode()])
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        # Give the reader thread a moment to process
        import time
        time.sleep(0.05)

        progress = runner.get_progress(rid)
        assert progress is not None
        assert progress["frame"] == 123
        assert progress["time_seconds"] == pytest.approx(4.10, rel=1e-3)

    def test_get_progress_returns_latest(self) -> None:
        """When multiple progress lines exist, the most recent is returned."""
        lines = [
            "frame=   1 fps=30.0 q=-1.0 size=      64KiB "
            "time=00:00:00.03 bitrate=17476.3kbits/s speed=0.997x\n",
            "frame=   2 fps=30.0 q=-1.0 size=     128KiB "
            "time=00:00:00.07 bitrate=14971.4kbits/s speed=0.998x\n",
        ]
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.stderr = iter([l.encode() for l in lines])
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        import time
        time.sleep(0.05)

        progress = runner.get_progress(rid)
        assert progress is not None
        assert progress["frame"] == 2


class TestFFmpegRunnerStop:
    """FFmpegRunner.stop_recording — graceful shutdown and transmux."""

    def test_sends_q_to_stdin(self) -> None:
        """stop_recording sends 'q\\n' to the process stdin."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4") as mock_tmux,
        ):
            mock_isfile.return_value = False
            runner.stop_recording(rid)

        proc.stdin.write.assert_called_with(b"q\n")
        proc.stdin.flush.assert_called_once()

    def test_waits_for_process(self) -> None:
        """stop_recording waits for the process to exit."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4") as mock_tmux,
        ):
            mock_isfile.return_value = False
            runner.stop_recording(rid)

        proc.wait.assert_called_once()

    def test_transmuxes_when_ts_exists(self) -> None:
        """When .ts file exists, transmux_to_mp4 is called and .ts is deleted."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.poll.side_effect = [None, None, 0]  # running x2, then exited
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4") as mock_tmux,
            patch("app.infrastructure.ffmpeg.process_runner.os.remove") as mock_remove,
        ):
            mock_isfile.return_value = True
            mock_tmux.return_value = True
            runner.stop_recording(rid)

        mock_tmux.assert_called_once_with("/data/test.ts", "/data/test.mp4")
        mock_remove.assert_called_once_with("/data/test.ts")

    def test_preserves_ts_on_transmux_failure(self) -> None:
        """When transmux fails, the .ts file is NOT deleted."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.poll.side_effect = [None, None, 0]  # running x2, then exited
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4") as mock_tmux,
            patch("app.infrastructure.ffmpeg.process_runner.os.remove") as mock_remove,
        ):
            mock_isfile.return_value = True
            mock_tmux.return_value = False
            runner.stop_recording(rid)

        mock_remove.assert_not_called()

    def test_stop_is_idempotent(self) -> None:
        """Stopping an already-stopped recording is a no-op."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            # poll is called twice during stop: once in _stop_one to check
            # if running, once in stop_ffmpeg_gracefully to check again.
            proc.poll.side_effect = [None, None, 0, 0]
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4"),
        ):
            mock_isfile.return_value = False
            runner.stop_recording(rid)
            runner.stop_recording(rid)  # second call — should be no-op

        # stdin.write should only be called once (by the first stop)
        proc.stdin.write.assert_called_once_with(b"q\n")


class TestFFmpegRunnerStopAll:
    """FFmpegRunner.stop_all — batch stop."""

    def test_stops_all_active_recordings(self) -> None:
        """stop_all stops every active recording."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc1 = _mock_process()
            proc2 = _mock_process()
            mock_popen.side_effect = [proc1, proc2]
            runner = FFmpegRunner()
            rid1 = runner.start_recording("url1", "/data/1.ts")
            rid2 = runner.start_recording("url2", "/data/2.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4"),
        ):
            mock_isfile.return_value = False
            runner.stop_all()

        assert runner.is_recording(rid1) is False
        assert runner.is_recording(rid2) is False

    def test_stop_all_on_empty_runner(self) -> None:
        """stop_all on a runner with no recordings is a no-op."""
        runner = FFmpegRunner()
        runner.stop_all()  # should not raise


class TestFFmpegRunnerEdgeCases:
    """Edge cases — crashed process, no stdin, etc."""

    def test_stop_crashed_process(self) -> None:
        """Stopping a process that already exited (poll!=None) is safe."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.poll.return_value = 0  # already exited
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4"),
        ):
            mock_isfile.return_value = False
            runner.stop_recording(rid)  # should not raise

        # stdin should NOT be written to for an already-exited process
        proc.stdin.write.assert_not_called()

    def test_stop_with_no_stdin(self) -> None:
        """If stdin is None (not piped), stop handles it gracefully."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.stdin = None
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4"),
        ):
            mock_isfile.return_value = False
            runner.stop_recording(rid)  # should not raise

    def test_stop_with_closed_stdin(self) -> None:
        """If stdin is closed, stop handles it gracefully."""
        with patch("app.infrastructure.ffmpeg.process_runner.subprocess.Popen") as mock_popen:
            proc = _mock_process()
            proc.stdin.closed = True
            mock_popen.return_value = proc
            runner = FFmpegRunner()
            rid = runner.start_recording("url", "/data/test.ts")

        with (
            patch("app.infrastructure.ffmpeg.process_runner.os.path.isfile") as mock_isfile,
            patch("app.infrastructure.ffmpeg.process_runner.transmux_to_mp4"),
        ):
            mock_isfile.return_value = False
            runner.stop_recording(rid)  # should not raise
