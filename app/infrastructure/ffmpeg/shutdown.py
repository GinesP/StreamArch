"""Graceful shutdown helpers for active ffmpeg processes.

Sends ``q`` to ffmpeg's stdin — the built-in graceful termination
mechanism documented in ``man ffmpeg``::

    Press [q] to stop, [?] for help

``q`` tells ffmpeg to finish the current GOP and exit cleanly, which
produces a valid (playable) recording even when stopping mid-stream.
"""

import logging
import subprocess
from typing import IO

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT: int = 10


def stop_ffmpeg_gracefully(
    process: subprocess.Popen,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> bool:
    """Send ``q`` to an ffmpeg process and wait for clean exit.

    Sends ``q`` to ``process.stdin``, then waits up to *timeout_seconds*
    for the process to exit.  If the timeout expires the process is
    killed.

    Args:
        process: A running :class:`subprocess.Popen` instance that was
                 started with ``stdin=subprocess.PIPE``.
        timeout_seconds: Maximum time (seconds) to wait for graceful exit.

    Returns:
        ``True`` if the process exited cleanly before the timeout,
        ``False`` if it had to be killed.
    """
    # Already finished — nothing to do.
    if process.poll() is not None:
        return True

    _send_q(process.stdin)

    try:
        process.wait(timeout=timeout_seconds)
        logger.info("ffmpeg stopped gracefully (pid=%d)", process.pid)
        return True
    except subprocess.TimeoutExpired:
        logger.warning(
            "ffmpeg pid=%d did not stop within %ds — killing",
            process.pid,
            timeout_seconds,
        )
        process.kill()
        process.wait()
        return False


# ── Internal helpers ───────────────────────────────────────────────────


def _send_q(stdin: IO[bytes] | None) -> None:
    """Write ``q`` to the process stdin, if available.

    Handles the case where stdin was not piped or is already closed
    without raising.
    """
    if stdin is None or stdin.closed:
        logger.debug("Cannot send q — stdin is None or closed")
        return

    try:
        stdin.write(b"q\n")
        stdin.flush()
    except OSError as exc:
        logger.warning("Could not write 'q' to ffmpeg stdin: %s", exc)
