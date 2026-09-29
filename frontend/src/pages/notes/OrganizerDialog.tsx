// "AI organize vault": preview the proposed moves, pick which to apply.

import { useState } from "react";
import { api } from "../../api";
import type { OrganizerPreview } from "../../types";

const moveKey = (move: { from: string; to: string }) => `${move.from}->${move.to}`;

export function useOrganizer({
  setError,
  onApplied,
}: {
  setError: (message: string | null) => void;
  /** After moves are applied (the open tabs may point at moved files). */
  onApplied: (applied: number) => Promise<void>;
}) {
  const [preview, setPreview] = useState<OrganizerPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const open = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.organizerPreview();
      setPreview(result);
      setSelected(new Set(result.moves.map(moveKey)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview?.moves.length || !selected.size) return;
    setBusy(true);
    try {
      const chosenMoves = preview.moves.filter((move) => selected.has(moveKey(move)));
      const result = await api.organizerApply(chosenMoves);
      setPreview(null);
      setSelected(new Set());
      await onApplied(result.applied);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return { preview, setPreview, selected, setSelected, busy, open, apply };
}

export function OrganizerDialog({ organizer }: { organizer: ReturnType<typeof useOrganizer> }) {
  const { preview, setPreview, selected, setSelected, busy, apply } = organizer;
  if (!preview) return null;
  return (
    <div className="organizer-backdrop">
      <div className="organizer-modal card">
        <div className="row">
          <div>
            <h2 className="page-title">AI organization preview</h2>
            <p className="page-sub">
              {preview.summary || "Review every proposed move before applying it."}
            </p>
          </div>
          <div className="grow" />
          <button onClick={() => setPreview(null)}>Close</button>
        </div>
        {preview.moves.length === 0 ? (
          <div className="note-banner">The AI did not recommend any safe moves.</div>
        ) : (
          <div className="organizer-table">
            <table>
              <thead>
                <tr>
                  <th className="organizer-select">
                    <input
                      type="checkbox"
                      aria-label="Select all organization moves"
                      checked={preview.moves.length > 0 && selected.size === preview.moves.length}
                      onChange={(event) =>
                        setSelected(
                          event.target.checked ? new Set(preview.moves.map(moveKey)) : new Set(),
                        )
                      }
                    />
                  </th>
                  <th>Before</th><th>After</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {preview.moves.map((move) => {
                  const key = moveKey(move);
                  return (
                    <tr key={key} className={selected.has(key) ? "" : "organizer-unselected"}>
                      <td className="organizer-select">
                        <input
                          type="checkbox"
                          aria-label={`Move ${move.from} to ${move.to}`}
                          checked={selected.has(key)}
                          onChange={(event) => {
                            setSelected((previous) => {
                              const next = new Set(previous);
                              event.target.checked ? next.add(key) : next.delete(key);
                              return next;
                            });
                          }}
                        />
                      </td>
                      <td><code>{move.from}</code></td>
                      <td><code>{move.to}</code></td>
                      <td className="muted">{move.reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="row organizer-actions">
          <span className="muted small">
            {selected.size} of {preview.moves.length} selected. Names are preserved exactly.
          </span>
          <div className="grow" />
          <button onClick={() => setPreview(null)}>Cancel</button>
          <button
            className="primary"
            onClick={apply}
            disabled={busy || selected.size === 0}
          >
            {busy ? "Applying…" : "Apply changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
