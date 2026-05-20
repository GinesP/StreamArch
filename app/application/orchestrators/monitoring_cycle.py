"""MonitoringCycle — top-level coordination of the monitoring loop.

1. Load active targets
2. Compute prediction
3. Apply scheduling policy
4. Enqueue checks
5. Process results
6. Update state and notify UI
"""


class MonitoringCycle:
    def run_cycle(self) -> None:
        """Execute one full monitoring iteration."""
        raise NotImplementedError
