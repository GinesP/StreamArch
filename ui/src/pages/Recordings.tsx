import { useCallback, useEffect, useState } from "react";
import type { RecordingSession } from "../types";
import { listRecordings } from "../api/recordings";

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function statusColor(status: string): string {
  switch (status) {
    case "recording":
      return "var(--recording)";
    case "completed":
      return "var(--accent)";
    case "failed":
    case "aborted":
      return "var(--error)";
    case "split":
      return "var(--warning)";
    default:
      return "var(--text-secondary)";
  }
}

export function Recordings() {
  const [items, setItems] = useState<RecordingSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStreamId, setFilterStreamId] = useState("");

  const fetch = useCallback(async (streamId?: string) => {
    setLoading(true);
    try {
      const data = await listRecordings(streamId || undefined);
      setItems(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load recordings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const handleFilter = () => {
    fetch(filterStreamId || undefined);
  };

  return (
    <div className="recordings">
      <div className="recordings-toolbar">
        <div className="filter-group">
          <input
            type="text"
            placeholder="Filter by stream ID..."
            value={filterStreamId}
            onChange={(e) => setFilterStreamId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleFilter()}
          />
          <button className="btn btn-sm" onClick={handleFilter}>
            Filter
          </button>
          {filterStreamId && (
            <button
              className="btn btn-sm"
              onClick={() => {
                setFilterStreamId("");
                fetch();
              }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="loading-text">Loading recordings...</div>
      ) : items.length === 0 ? (
        <div className="empty-state">No recordings found.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stream</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Status</th>
                <th>Platform</th>
                <th>Title</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td className="cell-mono">{r.stream_target_id.slice(0, 8)}…</td>
                  <td>{formatDate(r.started_at)}</td>
                  <td>{formatDuration(r.duration_seconds)}</td>
                  <td>
                    <span
                      className="status-badge"
                      style={{ color: statusColor(r.status) }}
                    >
                      {r.status}
                    </span>
                  </td>
                  <td>{r.source_platform}</td>
                  <td className="cell-mono" title={r.stream_title ?? ""}>
                    {r.stream_title ? (
                      r.stream_title.length > 40
                        ? r.stream_title.slice(0, 40) + "…"
                        : r.stream_title
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <style>{`
        .recordings {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .recordings-toolbar {
          display: flex;
          gap: 12px;
        }
        .filter-group {
          display: flex;
          gap: 6px;
          align-items: center;
        }
        .filter-group input {
          width: 280px;
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
        }
        .empty-state {
          color: var(--text-muted);
          text-align: center;
          padding: 48px 0;
        }
        .table-wrap {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          overflow-x: auto;
        }
        .cell-mono {
          font-family: inherit;
          font-size: 13px;
        }
        .status-badge {
          font-weight: 600;
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .text-muted {
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
}
