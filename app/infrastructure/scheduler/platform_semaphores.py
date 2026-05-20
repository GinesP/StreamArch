"""PlatformSemaphores — per-platform concurrency limits.

Prevents hitting rate limits by limiting how many concurrent checks
or recordings can run per platform.
"""


class PlatformSemaphores:
    def acquire(self, platform: str) -> bool:
        raise NotImplementedError

    def release(self, platform: str) -> None:
        raise NotImplementedError
