import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Recordings } from "./pages/Recordings";
import { Settings } from "./pages/Settings";

export default function App() {
  const [wsConnected, setWsConnected] = useState(false);

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout connected={wsConnected} />}>
          <Route
            index
            element={<Dashboard onWsStatus={setWsConnected} />}
          />
          <Route path="recordings" element={<Recordings />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
