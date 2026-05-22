import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";

interface Props {
  connected: boolean;
}

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/recordings": "Recordings",
  "/settings": "Settings",
};

export function Layout({ connected }: Props) {
  const location = useLocation();
  const title = PAGE_TITLES[location.pathname] ?? "StreamArch";

  return (
    <div className="layout">
      <Sidebar />
      <div className="layout-main">
        <Header connected={connected} title={title} />
        <main className="layout-content">
          <Outlet />
        </main>
      </div>
      <style>{`
        .layout {
          display: flex;
          height: 100%;
          width: 100%;
        }
        .layout-main {
          flex: 1;
          display: flex;
          flex-direction: column;
          min-width: 0;
        }
        .layout-content {
          flex: 1;
          overflow-y: auto;
          padding: 24px;
        }
      `}</style>
    </div>
  );
}
