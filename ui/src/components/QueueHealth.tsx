interface BandInfo {
  band: string;
  depth: number;
  color: string;
}

interface Props {
  bands?: BandInfo[];
}

export function QueueHealth({ bands }: Props) {
  if (!bands || bands.length === 0) return null;

  return (
    <div className="queue-health">
      <h3 className="section-title">Queue Health</h3>
      <div className="queue-bands">
        {bands.map((b) => (
          <div key={b.band} className="queue-band">
            <span
              className="queue-band-dot"
              style={{ background: b.color }}
            />
            <span className="queue-band-label">{b.band}</span>
            <span className="queue-band-depth">{b.depth}</span>
          </div>
        ))}
      </div>
      <style>{`
        .queue-health {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 16px;
        }
        .section-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 12px;
        }
        .queue-bands {
          display: flex;
          gap: 16px;
        }
        .queue-band {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .queue-band-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
        }
        .queue-band-label {
          font-size: 12px;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .queue-band-depth {
          font-size: 18px;
          font-weight: 700;
          color: var(--text-primary);
        }
      `}</style>
    </div>
  );
}
