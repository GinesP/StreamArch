import type {
  StreamItem,
  DashboardState,
  AddStreamPayload,
  ForceCheckResult,
} from "../types";

const BASE = "/api/v1";

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Streams CRUD ────────────────────────────────────────────────────────

export async function listStreams(): Promise<StreamItem[]> {
  const data = await request<{ items: StreamItem[] }>("/streams");
  return data.items;
}

export async function addStream(payload: AddStreamPayload): Promise<{ id: string }> {
  return request<{ id: string }>("/streams", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateStream(
  streamId: string,
  fields: Record<string, unknown>,
): Promise<void> {
  await request(`/streams/${streamId}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}

// ── Stream actions ──────────────────────────────────────────────────────

export async function disableMonitoring(streamId: string): Promise<void> {
  await request(`/streams/${streamId}/disable-monitoring`, {
    method: "POST",
  });
}

export async function enableMonitoring(streamId: string): Promise<void> {
  await request(`/streams/${streamId}/enable-monitoring`, {
    method: "POST",
  });
}

export async function forceCheck(
  streamId: string,
): Promise<ForceCheckResult> {
  return request<ForceCheckResult>(`/streams/${streamId}/force-check`, {
    method: "POST",
  });
}

export async function markFavorite(streamId: string): Promise<void> {
  await request(`/streams/${streamId}/favorite`, {
    method: "POST",
  });
}

export async function unmarkFavorite(streamId: string): Promise<void> {
  await request(`/streams/${streamId}/favorite`, {
    method: "DELETE",
  });
}

// ── Dashboard ───────────────────────────────────────────────────────────

export async function getDashboardState(): Promise<DashboardState> {
  return request<DashboardState>("/dashboard/state");
}
