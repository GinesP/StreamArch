interface Props {
  connected: boolean;
}

export function ConnectionIndicator({ connected }: Props) {
  return (
    <span className="connection-indicator">
      <span
        className={`connection-dot${connected ? " connected" : " disconnected"}`}
      />
      {connected ? "Connected" : "Disconnected"}
      <style>{`
        .connection-indicator {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          color: var(--text-secondary);
        }
        .connection-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
        }
        .connection-dot.connected {
          background: var(--accent);
          box-shadow: 0 0 6px var(--accent);
        }
        .connection-dot.disconnected {
          background: var(--danger);
          box-shadow: 0 0 6px var(--danger);
        }
      `}</style>
    </span>
  );
}
