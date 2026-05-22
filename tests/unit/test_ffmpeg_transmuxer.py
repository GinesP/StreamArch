"""Tests for the ffmpeg transmuxer module.

All tests mock ``subprocess.run`` to avoid depending on ffmpeg being
installed on the test runner.
"""

import subprocess
from unittest.mock import patch

import pytest

from app.infrastructure.ffmpeg.transmuxer import transmux_to_mp4


class TestTransmuxToMp4:
    """transmux_to_mp4 — happy paths and error handling."""

    def test_successful_transmux(self) -> None:
        """When ffmpeg returns rc=0, the function returns True."""
        with patch("app.infrastructure.ffmpeg.transmuxer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""

            result = transmux_to_mp4("/input.ts", "/output.mp4")

        assert result is True
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "-i" in cmd
        assert "/input.ts" in cmd
        assert "/output.mp4" in cmd
        assert "-c" in cmd and "copy" in cmd
        assert "-movflags" in cmd and "faststart" in cmd
        assert kwargs.get("timeout") == 300

    def test_ffmpeg_fails(self) -> None:
        """When ffmpeg returns non-zero, the function returns False."""
        with patch("app.infrastructure.ffmpeg.transmuxer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = b"error: invalid input"

            result = transmux_to_mp4("/input.ts", "/output.mp4")

        assert result is False

    def test_ffmpeg_not_found(self) -> None:
        """FileNotFoundError is re-raised."""
        with patch(
            "app.infrastructure.ffmpeg.transmuxer.subprocess.run",
            side_effect=FileNotFoundError("ffmpeg"),
        ):
            with pytest.raises(FileNotFoundError):
                transmux_to_mp4("/input.ts", "/output.mp4")

    def test_timeout(self) -> None:
        """subprocess.TimeoutExpired returns False."""
        with patch(
            "app.infrastructure.ffmpeg.transmuxer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10),
        ):
            result = transmux_to_mp4("/input.ts", "/output.mp4", timeout=10)
        assert result is False

    def test_os_error(self) -> None:
        """An OSError during subprocess.run returns False."""
        with patch(
            "app.infrastructure.ffmpeg.transmuxer.subprocess.run",
            side_effect=OSError(12, "Cannot allocate memory"),
        ):
            result = transmux_to_mp4("/input.ts", "/output.mp4")
        assert result is False

    def test_command_contains_expected_flags(self) -> None:
        """Verify the exact ffmpeg command line."""
        with patch("app.infrastructure.ffmpeg.transmuxer.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b""

            transmux_to_mp4("/data/recording.ts", "/data/recording.mp4")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert cmd[1] == "-i"
        assert cmd[2] == "/data/recording.ts"
        assert cmd[3] == "-c"
        assert cmd[4] == "copy"
        assert cmd[5] == "-movflags"
        assert cmd[6] == "faststart"
        assert cmd[7] == "-y"
        assert cmd[8] == "/data/recording.mp4"
