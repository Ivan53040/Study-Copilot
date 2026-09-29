import { useEffect, useState } from "react";
import { api } from "../../api";

/** Empty-tab note picker: search the vault and open a note into this tab. */
export function NewTabPicker({ onPick }: { onPick: (path: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ path: string; title: string }[]>([]);
  useEffect(() => {
    let alive = true;
    api
      .vaultSearch(q)
      .then((r) => alive && setResults(r.results.slice(0, 20)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [q]);
  return (
    <div className="newtab-picker">
      <input
        autoFocus
        placeholder="Search notes to open…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="newtab-results">
        {results.map((r) => (
          <div
            key={r.path}
            className="newtab-result"
            onClick={() => onPick(r.path)}
          >
            {r.title} <span className="muted small">· {r.path}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
