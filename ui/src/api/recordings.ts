import type { RecordingSession } from "../types";

const BASE = "/api/v1";

export async function listRecordings(
  streamId?: string,
): Promise<RecordingSession[]> {
  const query = streamId ? `?stream_id=${encodeURIComponent(streamId)}` : "";
  const res = await fetch(`${BASE}/recordings${query}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  const data: { items: RecordingSession[] } = await res.json();
  return data.items;
}
