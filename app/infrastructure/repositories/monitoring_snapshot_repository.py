"""MonitoringSnapshotRepository has been removed.

Monitoring snapshots are now in-memory only, owned by the
``MonitoringCycle``.  See ``app/application/orchestrators/monitoring_cycle.py``
and ``app/application/services/live_check_result_store.py``.
"""
