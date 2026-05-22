"""Transmux/remux from ``.ts`` to ``.mp4`` using ffmpeg ``-c copy``.

No re-encoding is performed — only the container format changes.  The
output MP4 uses ``-movflags faststart`` for web-optimised streaming.

Usage::

    success = transmux_to_mp4("/data/recording.ts", "/data/recording.mp4")
"""

import logging
import subprocess

logger = logging.getLogger(__name__)

# Default timeout for the transmux process (5 minutes).
_DEFAULT_TIMEOUT: int = 300


def transmux_to_mp4(
    input_path: str,
    output_path: str,
    timeout: int = _DEFAULT_TIMEOUT,
) -> bool:
    """Remux a ``.ts`` file to ``.mp4`` with ``-c copy`` (no re-encode).

    Uses ``-movflags faststart`` so the MP4 can be streamed over HTTP
    without waiting for the entire file to download.

    Args:
        input_path: Path to the source ``.ts`` file.
        output_path: Path for the output ``.mp4`` file.
        timeout: Maximum seconds to wait for the transmux process
                 (default: 300 / 5 minutes).

    Returns:
        ``True`` if transmux succeeded, ``False`` otherwise.

    Raises:
        FileNotFoundError: If ``ffmpeg`` is not on ``PATH``.
    """
    cmd: list[str] = [
        "ffmpeg",
        "-i", input_path,
        "-c", "copy",                   # No re-encode
        "-movflags", "faststart",       # Web-optimised MP4
        "-y",                           # Overwrite output
        output_path,
    ]

    logger.info("Transmuxing %s -> %s", input_path, output_path)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("ffmpeg not found on PATH — cannot transmux %s", input_path)
        raise
    except subprocess.TimeoutExpired:
        logger.error(
            "Transmux timed out after %ds: %s -> %s",
            timeout,
            input_path,
            output_path,
        )
        return False
    except OSError as exc:
        logger.error("Transmux OS error for %s: %s", input_path, exc)
        return False

    if result.returncode != 0:
        stderr_snippet = result.stderr.decode("utf-8", errors="replace")[-500:]
        logger.error(
            "Transmux failed (rc=%d): %s",
            result.returncode,
            stderr_snippet,
        )
        return False

    logger.info("Transmux complete: %s (size=%d bytes)", output_path, len(result.stdout))
    return True
