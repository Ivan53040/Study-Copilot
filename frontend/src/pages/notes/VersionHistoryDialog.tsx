// Version history: the backups kept before each save; restore any of them.

import { useState } from "react";
import { api } from "../../api";
import type { NoteVersion } from "../../types";

export function useVersionHistory({
  path,
  flash,
  reload,
}: {
  path: string | null;
  flash: (message: string) => void;
  reload: (path: string) => Promise<void>;
}) {
  const [versions, setVersions] = useState<NoteVersion[] | null>(null);

  const open = async () => {
    if (!path) return;
    try {
      const result = await api.vaultVersions(path);
      setVersions(result.versions);
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const restore = async (version: NoteVersion) => {
    if (!path) return;
    if (!window.confirm(`Restore the version from ${new Date(version.timestamp).toLocaleString()}?`)) return;
    try {
      await api.vaultRestoreVersion(path, version.id);
      await reload(path);
      setVersions(null);
      flash("Version restored");
    } catch (error) {
      flash((error as Error).message);
    }
  };

  return { versions, open, restore, close: () => setVersions(null) };
}

export function VersionHistoryDialog({
  history,
  path,
}: {
  history: ReturnType<typeof useVersionHistory>;
  path: string | null;
}) {
  const { versions, restore, close } = history;
  if (!versions) return null;
  return (
    <div className="organizer-backdrop">
      <div className="organizer-modal version-modal card">
        <div className="row">
          <div>
            <h2 className="page-title">Version history</h2>
            <p className="page-sub">{path}</p>
          </div>
          <div className="grow" />
          <button onClick={close}>Close</button>
        </div>
        <div className="version-list">
          {versions.length ? versions.map((version) => (
            <div className="version-entry" key={version.id}>
              <div className="row">
                <strong>{new Date(version.timestamp).toLocaleString()}</strong>
                <span className="muted small">{version.size.toLocaleString()} bytes</span>
                <div className="grow" />
                <button onClick={() => restore(version)}>Restore</button>
              </div>
              <pre>{version.content.slice(0, 1200)}</pre>
            </div>
          )) : (
            <div className="note-banner">No earlier saved versions yet.</div>
          )}
        </div>
      </div>
    </div>
  );
}
