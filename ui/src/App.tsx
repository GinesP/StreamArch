import { BrowserRouter, Routes, Route } from "react-router-dom";
import { WsProvider, useWsStatus } from "./WsContext";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Recordings } from "./pages/Recordings";
import { Settings } from "./pages/Settings";

/** Inner component that reads WS status from context. */
function AppContent() {
  const { connected } = useWsStatus();

  return (
    <Routes>
      <Route element={<Layout connected={connected} />}>
        <Route index element={<Dashboard />} />
        <Route path="recordings" element={<Recordings />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <WsProvider>
        <AppContent />
      </WsProvider>
    </BrowserRouter>
  );
}
