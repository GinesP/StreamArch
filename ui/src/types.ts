// ── Backend API response types ──────────────────────────────────────────

export interface StreamItem {
  id: string;
  platform: Platform;
  handle: string;
  display_name: string;
  enabled: boolean;
  favorite: boolean;
  state: MonitoringState;
  queue_band: QueueBand | null;
  current_likelihood: number;
  current_confidence: Confidence;
  next_check_at: string | null;
  last_live_at: string | null;
}

export type Platform = "twitch" | "tiktok" | "youtube" | "kick" | "other";
export type MonitoringState =
  | "idle"
  | "checking"
  | "recording"
  | "post_processing"
  | "error"
  | "unknown";
export type QueueBand = "fast" | "medium" | "slow";
export type Confidence = "low" | "medium" | "high";
export type RecordingStatus =
  | "recording"
  | "completed"
  | "failed"
  | "aborted"
  | "split";

export interface DashboardState {
  streams: StreamItem[];
  total_count: number;
  live_count: number;
  error_count: number;
  idle_count: number;
}

export interface RecordingSession {
  id: string;
  stream_target_id: string;
  started_at: string;
  ended_at: string | null;
  status: RecordingStatus;
  source_platform: string;
  stream_title: string | null;
  duration_seconds: number | null;
  detected_by_queue: string | null;
  error_code: string | null;
  error_message: string | null;
  split_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface AddStreamPayload {
  platform: string;
  handle: string;
  source_url: string;
  display_name: string;
  preferred_quality?: string;
  output_profile_id?: string;
  schedule_mode?: string;
}

export interface ForceCheckResult {
  stream_id: string;
  is_live: boolean;
  stream_url: string | null;
  title: string | null;
  anchor_name: string | null;
  m3u8_url: string | null;
}

export interface ImportCookiePayload {
  platform: string;
  file_path: string;
}

export interface ImportCookieResult {
  status: string;
  platform: string;
  count: number;
}

// ── WebSocket event envelope ────────────────────────────────────────────

export interface WsEnvelope {
  seq: number;
  type: WsEventType;
  timestamp: string;
  payload: Record<string, unknown>;
}

export type WsEventType =
  | "stream.status_changed"
  | "stream.forecast_updated"
  | "recording.started"
  | "recording.progress"
  | "recording.finished"
  | "postprocess.updated"
  | "queue.health_updated"
  | "queue.cycle_stats"
  | "system.alert"
  | "system.core_ready";
