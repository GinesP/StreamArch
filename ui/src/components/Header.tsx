import { ConnectionIndicator } from "./ConnectionIndicator";

interface Props {
  connected: boolean;
  title?: string;
}

export function Header({ connected, title }: Props) {
  return (
    <header className="header">
      <h1 className="header-title">{title ?? "Dashboard"}</h1>
      <ConnectionIndicator connected={connected} />
      <style>{`
        .header {
          height: var(--header-height);
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 24px;
          border-bottom: 1px solid var(--border);
          background: var(--bg-primary);
          flex-shrink: 0;
        }
        .header-title {
          font-size: 16px;
          font-weight: 600;
          color: var(--text-primary);
        }
      `}</style>
    </header>
  );
}
