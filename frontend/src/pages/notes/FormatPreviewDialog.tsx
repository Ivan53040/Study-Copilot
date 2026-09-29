// "AI format document": preview the model's reformatted Markdown side by side
// with the original, then apply it (a recoverable version is kept).

import { useState } from "react";
import { api } from "../../api";
import type { FormatPreview } from "../../types";

export function useFormatPreview({
  path,
  currentContent,
  setError,
  flash,
  reload,
}: {
  path: string | null;
  /** The text to format: the draft while editing, else the saved note. */
  currentContent: () => string;
  setError: (message: string | null) => void;
  flash: (message: string) => void;
  reload: (path: string) => Promise<void>;
}) {
  const [preview, setPreview] = useState<FormatPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const open = async () => {
    if (!path) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await api.formatPreview(path, currentContent()));
    } catch (error) {
      flash((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!path || !preview) return;
    setBusy(true);
    try {
      await api.vaultSaveNote(path, preview.after);
      await reload(path);
      setPreview(null);
      flash("AI formatting applied");
    } catch (error) {
      flash((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return { preview, busy, open, apply, close: () => setPreview(null) };
}

export function FormatPreviewDialog({ format }: { format: ReturnType<typeof useFormatPreview> }) {
  const { preview, busy, apply, close } = format;
  if (!preview) return null;
  return (
    <div className="organizer-backdrop">
      <div className="organizer-modal format-modal card">
        <div className="row">
          <div>
            <h2 className="page-title">AI formatting preview</h2>
            <p className="page-sub">
              Review the original and formatted Markdown before applying.
            </p>
          </div>
          <div className="grow" />
          <button onClick={close}>Close</button>
        </div>
        <div className="format-comparison">
          <section>
            <h3>Before</h3>
            <pre>{preview.before}</pre>
          </section>
          <section>
            <h3>After</h3>
            <pre>{preview.after}</pre>
          </section>
        </div>
        <div className="row organizer-actions">
          <span className="muted small">
            Model: {preview.model}. Applying creates a recoverable version.
          </span>
          <div className="grow" />
          <button onClick={close}>Cancel</button>
          <button
            className="primary"
            onClick={apply}
            disabled={busy || !preview.changed}
          >
            {busy ? "Applying…" : preview.changed ? "Apply formatting" : "No changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
