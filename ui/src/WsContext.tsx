import { createContext, useContext, useEffect, useRef, useState } from "react";
import { WsClient } from "./api/ws";
import type { WsEnvelope } from "./types";

// ── Context value type ──────────────────────────────────────────────────

interface WsContextValue {
  connected: boolean;
  /** Incremented on each event that should trigger a UI refresh. */
  refreshKey: number;
  /** The most recent WS envelope received (null before first event). */
  lastEnvelope: WsEnvelope | null;
}

const WsContext = createContext<WsContextValue>({
  connected: false,
  refreshKey: 0,
  lastEnvelope: null,
});

// ── Events that should cause a UI data refresh ──────────────────────────

const REFRESH_EVENTS = new Set<WsEnvelope["type"]>([
  "stream.status_changed",
  "stream.forecast_updated",
  "recording.started",
  "recording.finished",
  "queue.health_updated",
  "system.core_ready",
]);

// ── Provider ────────────────────────────────────────────────────────────

export function WsProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastEnvelope, setLastEnvelope] = useState<WsEnvelope | null>(null);
  const clientRef = useRef<WsClient | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/events`;

    const client = new WsClient(
      wsUrl,
      (envelope) => {
        setLastEnvelope(envelope);
        if (REFRESH_EVENTS.has(envelope.type)) {
          setRefreshKey((k) => k + 1);
        }
      },
      (status) => {
        setConnected(status);
        if (status) {
          // Trigger immediate data refresh on reconnection
          setRefreshKey((k) => k + 1);
        }
      },
    );
    clientRef.current = client;

    return () => {
      client.destroy();
      clientRef.current = null;
    };
  }, []);

  return (
    <WsContext.Provider value={{ connected, refreshKey, lastEnvelope }}>
      {children}
    </WsContext.Provider>
  );
}

// ── Hook ────────────────────────────────────────────────────────────────

export function useWsStatus(): WsContextValue {
  return useContext(WsContext);
}
