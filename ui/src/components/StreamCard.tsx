import { useState } from "react";
import type { StreamItem } from "../types";
import * as streams from "../api/streams";

interface Props {
  stream: StreamItem;
  onUpdated: () => void;
}

function platformIcon(platform: string): string {
  const icons: Record<string, string> = {
    twitch: "▲",
    tiktok: "♪",
    youtube: "▶",
    kick: "K",
  };
  return icons[platform] ?? "?";
}

function stateColor(state: string): string {
  switch (state) {
    case "live":
    case "recording":
      return "var(--live)";
    case "checking":
      return "var(--checking)";
    case "error":
      return "var(--error)";
    default:
      return "var(--idle)";
  }
}

function stateLabel(state: string): string {
  return state.replace(/_/g, " ");
}

function formatLikelihood(v: number): string {
  if (v == null || isNaN(v)) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

export function StreamCard({ stream, onUpdated }: Props) {
  const [loading, setLoading] = useState(false);

  const handleAction = async (
    action: () => Promise<unknown>,
  ) => {
    if (loading) return;
    setLoading(true);
    try {
      await action();
      onUpdated();
    } catch (err) {
      console.error(`Action failed for ${stream.display_name}:`, err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`stream-card${loading ? " loading" : ""}`}>
      <div className="card-top">
        <span className="platform-icon">{platformIcon(stream.platform)}</span>
        <div className="card-info">
          <span className="card-name">{stream.display_name}</span>
          <span className="card-handle">@{stream.handle}</span>
        </div>
        <span
          className="state-indicator"
          style={{ background: stateColor(stream.state) }}
          title={stateLabel(stream.state)}
        />
      </div>

      <div className="card-body">
        <div className="card-stat">
          <span className="stat-label">State</span>
          <span className="stat-value" style={{ color: stateColor(stream.state) }}>
            {stateLabel(stream.state)}
          </span>
        </div>
        <div className="card-stat">
          <span className="stat-label">Likelihood</span>
          <span className="stat-value">{formatLikelihood(stream.current_likelihood)}</span>
        </div>
        <div className="card-stat">
          <span className="stat-label">Queue</span>
          <span className="stat-value">
            {stream.queue_band ? stream.queue_band.toUpperCase() : "—"}
          </span>
        </div>
        <div className="card-stat">
          <span className="stat-label">Confidence</span>
          <span className="stat-value">{stream.current_confidence}</span>
        </div>
      </div>

      <div className="likelihood-bar">
        <div
          className="likelihood-fill"
          style={{
            width: `${(stream.current_likelihood * 100).toFixed(0)}%`,
            background: stateColor(stream.state),
          }}
        />
      </div>

      <div className="card-footer">
        {stream.enabled ? (
          <button
            className="btn btn-sm btn-danger"
            onClick={() => handleAction(() => streams.disableMonitoring(stream.id))}
            disabled={loading}
          >
            Disable
          </button>
        ) : (
          <button
            className="btn btn-sm btn-accent"
            onClick={() => handleAction(() => streams.enableMonitoring(stream.id))}
            disabled={loading}
          >
            Enable
          </button>
        )}
        <button
          className="btn btn-sm"
          onClick={() =>
            handleAction(() =>
              stream.favorite
                ? streams.unmarkFavorite(stream.id)
                : streams.markFavorite(stream.id),
            )
          }
          disabled={loading}
          title={stream.favorite ? "Unfavorite" : "Favorite"}
        >
          {stream.favorite ? "★" : "☆"}
        </button>
        <button
          className="btn btn-sm"
          onClick={() => handleAction(() => streams.forceCheck(stream.id))}
          disabled={loading}
          title="Force check now"
        >
          ↻
        </button>
      </div>

      <div className="card-meta">
        {stream.next_check_at && (
          <span>Next check: {new Date(stream.next_check_at).toLocaleString()}</span>
        )}
        {stream.last_live_at && (
          <span>Last live: {new Date(stream.last_live_at).toLocaleString()}</span>
        )}
      </div>

      <style>{`
        .stream-card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          transition: opacity var(--transition);
        }
        .stream-card.loading {
          opacity: 0.6;
          pointer-events: none;
        }
        .card-top {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .platform-icon {
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--bg-input);
          border-radius: var(--radius-sm);
          font-size: 16px;
          color: var(--text-secondary);
          flex-shrink: 0;
        }
        .card-info {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
        }
        .card-name {
          font-weight: 600;
          font-size: 15px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .card-handle {
          font-size: 12px;
          color: var(--text-muted);
        }
        .state-indicator {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          flex-shrink: 0;
          box-shadow: 0 0 6px currentColor;
        }
        .card-body {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
        }
        .card-stat {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .stat-label {
          font-size: 11px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .stat-value {
          font-size: 13px;
          font-weight: 500;
        }
        .likelihood-bar {
          height: 4px;
          background: var(--bg-input);
          border-radius: 2px;
          overflow: hidden;
        }
        .likelihood-fill {
          height: 100%;
          border-radius: 2px;
          transition: width 300ms ease;
          opacity: 0.7;
        }
        .card-footer {
          display: flex;
          gap: 6px;
        }
        .card-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 4px 12px;
          font-size: 11px;
          color: var(--text-muted);
        }
      `}</style>
    </div>
  );
}
