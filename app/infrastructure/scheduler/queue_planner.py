"""QueuePlanner — assigns targets to fast/medium/slow queues.

Responsible for:
    - Classifying streamers into queue bands
    - Ordering by effective priority
    - Respecting platform semaphores
    - Avoiding starvation
"""


class QueuePlanner:
    def plan(self) -> dict:
        """Return queue distribution for current cycle."""
        raise NotImplementedError
