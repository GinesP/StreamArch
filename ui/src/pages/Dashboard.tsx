import { useCallback, useEffect, useRef, useState } from "react";
import type { StreamItem, QueueBand } from "../types";
import * as streams from "../api/streams";
import { WsClient } from "../api/ws";
import { StreamCard } from "../components/StreamCard";
import { AddStreamModal } from "../components/AddStreamModal";
import { QueueHealth } from "../components/QueueHealth";

interface BandDepth {
  band: string;
  depth: number;
  color: string;
}

const BAND_COLORS: Record<string, string> = {
  fast: "var(--live)",
  medium: "var(--warning)",
  slow: "var(--idle)",
};

interface Props {
  onWsStatus: (connected: boolean) => void;
}

export function Dashboard({ onWsStatus }: Props) {
  const [items, setItems] = useState<StreamItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [queueBands, setQueueBands] = useState<BandDepth[]>([]);
  const wsRef = useRef<WsClient | null>(null);

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

  // Initial fetch
  useEffect(() => {
    fetchStreams();
  }, [fetchStreams]);

  // WebSocket for real-time updates
  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/events`;
    const client = new WsClient(wsUrl,
      (envelope) => {
        // Refresh stream data on relevant events
        const refreshEvents = new Set([
          "stream.status_changed",
          "stream.forecast_updated",
          "recording.started",
          "recording.finished",
          "queue.health_updated",
        ]);
        if (refreshEvents.has(envelope.type)) {
          fetchStreams();
        }
      },
      (connected) => {
        onWsStatus(connected);
      },
    );
    wsRef.current = client;

    return () => {
      client.destroy();
      wsRef.current = null;
    };
  }, [fetchStreams, onWsStatus]);

  return (
    <div className="dashboard">
      <div className="dashboard-top">
        <QueueHealth bands={queueBands} />
        <button
          className="btn btn-accent"
          onClick={() => setShowAddModal(true)}
        >
          + Add Stream
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="loading-text">Loading streams...</div>
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
        .stream-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
        }
      `}</style>
    </div>
  );
}
