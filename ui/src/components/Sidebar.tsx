import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/recordings", label: "Recordings" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">StreamArch</div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `sidebar-link${isActive ? " active" : ""}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <style>{`
        .sidebar {
          width: var(--sidebar-width);
          height: 100%;
          background: var(--bg-sidebar);
          border-right: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          flex-shrink: 0;
        }
        .sidebar-brand {
          font-size: 18px;
          font-weight: 700;
          color: var(--accent);
          padding: 16px 20px;
          border-bottom: 1px solid var(--border);
          letter-spacing: 0.5px;
        }
        .sidebar-nav {
          display: flex;
          flex-direction: column;
          padding: 12px 0;
          gap: 2px;
        }
        .sidebar-link {
          padding: 10px 20px;
          color: var(--text-secondary);
          font-size: 14px;
          transition: background var(--transition), color var(--transition);
          border-left: 3px solid transparent;
        }
        .sidebar-link:hover {
          color: var(--text-primary);
          background: var(--bg-card);
        }
        .sidebar-link.active {
          color: var(--accent);
          background: var(--bg-card);
          border-left-color: var(--accent);
        }
      `}</style>
    </aside>
  );
}
