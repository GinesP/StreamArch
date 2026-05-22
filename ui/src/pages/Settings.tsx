import { useCallback, useEffect, useState } from "react";
import * as cookies from "../api/cookies";

interface PlatformInfo {
  platform: string;
  has_cookies: boolean;
}

export function Settings() {
  const [platforms, setPlatforms] = useState<PlatformInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Import form state
  const [importPlatform, setImportPlatform] = useState("twitch");
  const [importPath, setImportPath] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<string | null>(null);

  const fetchPlatforms = useCallback(async () => {
    try {
      const names = await cookies.listCookiePlatforms();
      // Get detailed info for each platform
      const infos: PlatformInfo[] = await Promise.all(
        names.map(async (name) => {
          try {
            const detail = await cookies.getCookiePlatform(name);
            return { platform: name, has_cookies: detail.has_cookies };
          } catch {
            return { platform: name, has_cookies: false };
          }
        }),
      );
      setPlatforms(infos);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load cookie platforms",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlatforms();
  }, [fetchPlatforms]);

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    setImportResult(null);
    if (!importPath.trim()) return;

    setImporting(true);
    try {
      const result = await cookies.importCookies({
        platform: importPlatform,
        file_path: importPath,
      });
      setImportResult(
        `Imported ${result.count} cookies for ${result.platform}`,
      );
      setImportPath("");
      fetchPlatforms();
    } catch (err) {
      setImportResult(
        `Error: ${err instanceof Error ? err.message : "Import failed"}`,
      );
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="settings">
      <section className="settings-section">
        <h2>Cookie Platforms</h2>
        {error && <div className="error-banner">{error}</div>}
        {loading ? (
          <div className="loading-text">Loading...</div>
        ) : (
          <div className="platform-list">
            {platforms.map((p) => (
              <div key={p.platform} className="platform-item">
                <span className="platform-name">{p.platform}</span>
                <span
                  className={`platform-status${p.has_cookies ? " has" : ""}`}
                >
                  {p.has_cookies ? "✓ Cookies stored" : "No cookies"}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="settings-section">
        <h2>Import Cookies</h2>
        <form className="import-form" onSubmit={handleImport}>
          <label className="field">
            <span>Platform</span>
            <select
              value={importPlatform}
              onChange={(e) => setImportPlatform(e.target.value)}
            >
              {platforms.map((p) => (
                <option key={p.platform} value={p.platform}>
                  {p.platform}
                </option>
              ))}
              <option value="twitch">twitch</option>
              <option value="tiktok">tiktok</option>
              <option value="youtube">youtube</option>
              <option value="kick">kick</option>
            </select>
          </label>
          <label className="field">
            <span>Cookie File Path</span>
            <input
              type="text"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="/path/to/cookies.json"
            />
          </label>
          <button
            type="submit"
            className="btn btn-accent"
            disabled={importing || !importPath.trim()}
          >
            {importing ? "Importing..." : "Import"}
          </button>
          {importResult && (
            <div
              className={`import-result${importResult.startsWith("Error") ? " error" : ""}`}
            >
              {importResult}
            </div>
          )}
        </form>
      </section>

      <style>{`
        .settings {
          display: flex;
          flex-direction: column;
          gap: 24px;
          max-width: 640px;
        }
        .settings-section {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 20px;
        }
        .settings-section h2 {
          font-size: 15px;
          font-weight: 600;
          margin-bottom: 16px;
          color: var(--text-primary);
        }
        .error-banner {
          padding: 8px 12px;
          background: rgba(255, 82, 82, 0.1);
          border: 1px solid var(--danger);
          border-radius: var(--radius-sm);
          color: var(--danger);
          font-size: 13px;
          margin-bottom: 12px;
        }
        .loading-text {
          color: var(--text-secondary);
        }
        .platform-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .platform-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 12px;
          background: var(--bg-input);
          border-radius: var(--radius-sm);
        }
        .platform-name {
          font-weight: 600;
          text-transform: capitalize;
        }
        .platform-status {
          font-size: 12px;
          color: var(--text-muted);
        }
        .platform-status.has {
          color: var(--accent);
        }
        .import-form {
          display: flex;
          flex-direction: column;
          gap: 12px;
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
        .import-result {
          padding: 8px 10px;
          border-radius: var(--radius-sm);
          font-size: 13px;
          background: rgba(0, 230, 118, 0.1);
          border: 1px solid var(--accent);
          color: var(--accent);
        }
        .import-result.error {
          background: rgba(255, 82, 82, 0.1);
          border-color: var(--danger);
          color: var(--danger);
        }
      `}</style>
    </div>
  );
}
