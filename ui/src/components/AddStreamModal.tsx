import { useState } from "react";
import type { AddStreamPayload, Platform } from "../types";

const PLATFORMS: Platform[] = ["twitch", "tiktok", "youtube", "kick", "other"];

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function AddStreamModal({ open, onClose, onCreated }: Props) {
  const [form, setForm] = useState<AddStreamPayload>({
    platform: "twitch",
    handle: "",
    source_url: "",
    display_name: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!form.handle.trim() || !form.source_url.trim() || !form.display_name.trim()) {
      setError("Handle, source URL, and display name are required.");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch("/api/v1/streams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "Unknown error");
        throw new Error(`${res.status}: ${text}`);
      }
      onCreated();
      onClose();
      setForm({ platform: "twitch", handle: "", source_url: "", display_name: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create stream");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Add Stream</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <label className="field">
              <span>Platform</span>
              <select
                name="platform"
                value={form.platform}
                onChange={handleChange}
              >
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Display Name *</span>
              <input
                name="display_name"
                value={form.display_name}
                onChange={handleChange}
                placeholder="Streamer name"
              />
            </label>
            <label className="field">
              <span>Handle *</span>
              <input
                name="handle"
                value={form.handle}
                onChange={handleChange}
                placeholder="streamer_handle"
              />
            </label>
            <label className="field">
              <span>Source URL *</span>
              <input
                name="source_url"
                value={form.source_url}
                onChange={handleChange}
                placeholder="https://twitch.tv/..."
              />
            </label>
            <label className="field">
              <span>Preferred Quality</span>
              <input
                name="preferred_quality"
                value={form.preferred_quality ?? ""}
                onChange={handleChange}
                placeholder="e.g. 1080p60"
              />
            </label>
            <label className="field">
              <span>Schedule Mode</span>
              <select
                name="schedule_mode"
                value={form.schedule_mode ?? "none"}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    schedule_mode: e.target.value === "none" ? undefined : e.target.value,
                  }))
                }
              >
                <option value="none">None</option>
                <option value="regular">Regular</option>
                <option value="flexible">Flexible</option>
              </select>
            </label>
            {error && <div className="form-error">{error}</div>}
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="btn"
              onClick={onClose}
              disabled={saving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-accent"
              disabled={saving}
            >
              {saving ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
      <style>{`
        .modal-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.6);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
        }
        .modal {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          width: 440px;
          max-width: 90vw;
          max-height: 85vh;
          overflow-y: auto;
        }
        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid var(--border);
        }
        .modal-header h2 {
          font-size: 16px;
          font-weight: 600;
        }
        .modal-close {
          background: none;
          color: var(--text-secondary);
          font-size: 22px;
          line-height: 1;
          padding: 0 4px;
        }
        .modal-close:hover {
          color: var(--text-primary);
        }
        .modal-body {
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .field span {
          font-size: 12px;
          color: var(--text-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .form-error {
          padding: 8px 10px;
          background: rgba(255, 82, 82, 0.1);
          border: 1px solid var(--danger);
          border-radius: var(--radius-sm);
          color: var(--danger);
          font-size: 13px;
        }
        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          padding: 12px 20px;
          border-top: 1px solid var(--border);
        }
      `}</style>
    </div>
  );
}
