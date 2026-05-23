import { useCallback, useEffect, useState } from "react";
import type { StreamItem, QueueBand } from "../types";
import * as streams from "../api/streams";
import { useWsStatus } from "../WsContext";
import { StreamCard } from "../components/StreamCard";
import { AddStreamModal } from "../components/AddStreamModal";
import { QueueHealth } from "../components/QueueHealth";

interface BandDepth {
  band: string;
  depth: number;
  color: string;
}

interface CycleStats {
  enqueued: Record<string, number>;
  waiting: Record<string, number>;
  cycle_timestamp: string;
}

const BAND_COLORS: Record<string, string> = {
  fast: "var(--live)",
  medium: "var(--warning)",
  slow: "var(--idle)",
};

export function Dashboard() {
  const [items, setItems] = useState<StreamItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [queueBands, setQueueBands] = useState<BandDepth[]>([]);
  const [cycleStats, setCycleStats] = useState<CycleStats | null>(null);
  const [enqueuedHistory, setEnqueuedHistory] = useState<number[]>([]);
  const { connected, refreshKey, lastEnvelope } = useWsStatus();

  const fetchStreams = useCallback(async () => {
    try {
      const data = await streams.listStreams();
      setItems(data);
      setError(null);

      // Compute queue depths from all streams
      const depths: Record<string, number> = {};
      for (const s of data) {
        if (s.queue_band) {
          depths[s.queue_band] = (depths[s.queue_band] ?? 0) + 1;
        }
      }
      setQueueBands(
        (["fast", "medium", "slow"] as QueueBand[]).map((band) => ({
          band,
          depth: depths[band] ?? 0,
          color: BAND_COLORS[band] ?? "var(--idle)",
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load streams");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch + refresh on WS events (refreshKey changes)
  useEffect(() => {
    fetchStreams();
  }, [fetchStreams, refreshKey]);

  // When core disconnects, invalidate stale dashboard data so no card
  // shows a stale "recording" state or old snapshot data.
  useEffect(() => {
    if (!connected && items.length > 0) {
      setItems([]);
    }
  }, [connected]);

  // Watch for cycle stats events and update display
  useEffect(() => {
    if (lastEnvelope?.type === "queue.cycle_stats") {
      const payload = lastEnvelope.payload as unknown as CycleStats;
      setCycleStats(payload);
      const total = Object.values(payload.enqueued).reduce((a, b) => a + b, 0);
      setEnqueuedHistory((prev) => {
        const next = [...prev, total];
        if (next.length > 20) next.shift();
        return next;
      });
    }
  }, [lastEnvelope]);

  return (
    <div className="dashboard">
      <div className="dashboard-top">
        <QueueHealth bands={queueBands} />
        <button
          className="btn btn-accent"
          onClick={() => setShowAddModal(true)}
          disabled={!connected}
          title={!connected ? "Core is disconnected" : undefined}
        >
          + Add Stream
        </button>
      </div>

      {cycleStats && (
        <div className="cycle-stats">
          <div className="cycle-stats-row">
            <span className="cycle-stats-label">Enqueued ↑</span>
            <span className="cycle-stat" style={{ color: BAND_COLORS.fast }}>
              F {cycleStats.enqueued.fast ?? 0}
            </span>
            <span className="cycle-stat" style={{ color: BAND_COLORS.medium }}>
              M {cycleStats.enqueued.medium ?? 0}
            </span>
            <span className="cycle-stat" style={{ color: BAND_COLORS.slow }}>
              S {cycleStats.enqueued.slow ?? 0}
            </span>
          </div>
          <div className="cycle-stats-row">
            <span className="cycle-stats-label">Waiting</span>
            <span className="cycle-stat" style={{ color: BAND_COLORS.fast }}>
              F {cycleStats.waiting.fast ?? 0}
            </span>
            <span className="cycle-stat" style={{ color: BAND_COLORS.medium }}>
              M {cycleStats.waiting.medium ?? 0}
            </span>
            <span className="cycle-stat" style={{ color: BAND_COLORS.slow }}>
              S {cycleStats.waiting.slow ?? 0}
            </span>
          </div>
          <div className="cycle-stats-row">
            <span className="cycle-stats-label">Dispatched / Cycle</span>
            <span className="cycle-stat" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              {enqueuedHistory.length > 0 ? (
                <>
                  <span className="sparkline">
                    {(() => {
                      const mx = Math.max(...enqueuedHistory, 1);
                      return enqueuedHistory.map((v, i) => (
                        <span
                          key={i}
                          className="sparkline-bar"
                          style={{ height: `${(v / mx) * 100}%` }}
                        />
                      ));
                    })()}
                  </span>
                  <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                    {enqueuedHistory[enqueuedHistory.length - 1]}
                  </span>
                </>
              ) : (
                "—"
              )}
            </span>
          </div>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="loading-text">Loading streams...</div>
      ) : !connected ? (
        <div className="empty-state disconnected">
          Core disconnected. Waiting for connection...
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          No streams configured yet. Click "Add Stream" to get started.
        </div>
      ) : (
        <div className="stream-grid">
          {items.map((stream) => (
            <StreamCard
              key={stream.id}
              stream={stream}
              onUpdated={fetchStreams}
            />
          ))}
        </div>
      )}

      <AddStreamModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onCreated={fetchStreams}
      />

      <style>{`
        .dashboard {
          display: flex;
          flex-direction: column;
          gap: 20px;
          max-width: 1200px;
        }
        .dashboard-top {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
        }
        .error-banner {
          padding: 10px 14px;
          background: rgba(255, 82, 82, 0.1);
          border: 1px solid var(--danger);
          border-radius: var(--radius-sm);
          color: var(--danger);
          font-size: 13px;
        }
        .loading-text {
          color: var(--text-secondary);
          font-size: 14px;
        }
        .empty-state {
          color: var(--text-muted);
          font-size: 14px;
          text-align: center;
          padding: 48px 0;
        }
        .cycle-stats {
          display: flex;
          gap: 24px;
          flex-wrap: wrap;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: var(--radius-sm);
          padding: 12px 16px;
        }
        .cycle-stats-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .cycle-stats-label {
          color: var(--text-secondary);
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-right: 4px;
        }
        .cycle-stat {
          font-size: 14px;
          font-weight: 700;
          font-variant-numeric: tabular-nums;
        }
        .sparkline {
          display: inline-flex;
          align-items: flex-end;
          gap: 2px;
          height: 24px;
        }
        .sparkline-bar {
          width: 4px;
          background: var(--accent);
          border-radius: 1px 1px 0 0;
          min-height: 2px;
        }
        .empty-state.disconnected {
          color: var(--danger);
        }
        .stream-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
        }
      `}</style>
    </div>
  );
}
