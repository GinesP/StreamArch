import type { ImportCookiePayload, ImportCookieResult } from "../types";

const BASE = "/api/v1";

export async function listCookiePlatforms(): Promise<string[]> {
  const res = await fetch(`${BASE}/cookies`);
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  const data: { platforms: string[] } = await res.json();
  return data.platforms;
}

export async function importCookies(
  payload: ImportCookiePayload,
): Promise<ImportCookieResult> {
  const res = await fetch(`${BASE}/cookies/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<ImportCookieResult>;
}

export async function getCookiePlatform(
  platform: string,
): Promise<{ platform: string; cookie_string: string; has_cookies: boolean }> {
  const res = await fetch(`${BASE}/cookies/${encodeURIComponent(platform)}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}
