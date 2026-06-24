import { useEffect, useState } from "react";
import { api } from "../api";
import type { DocumentRow, VaultScope } from "../types";
import { TrustBadge } from "../components";
import { CoursePicker } from "../CoursePicker";

export function LibraryPage() {
  const [selected, setSelected] = useState<VaultScope | null>(null);
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) return;
    api
      .scopeDocuments(selected.path)
      .then((result) => setDocs(result.documents))
      .catch((e) => setError((e as Error).message));
  }, [selected]);

  return (
    <div>
      <h1 className="page-title">Library</h1>
      <p className="page-sub">Browse indexed documents from any course or vault folder.</p>
      {error && <div className="warn-banner">{error}</div>}
      <div className="course-toolbar">
        <CoursePicker value={selected} onChange={setSelected} />
        {selected && <span className="muted small">{docs.length} documents</span>}
      </div>
      {selected && docs.length === 0 && <div className="note-banner">No indexed documents in this scope.</div>}
      {docs.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Title</th><th>Week</th><th>Type</th><th>Trust</th><th>Chunks</th></tr></thead>
            <tbody>
              {docs.map((document) => (
                <tr key={document.id}>
                  <td>{document.title}</td>
                  <td>{document.week ?? "—"}</td>
                  <td className="muted">{document.document_type ?? "—"}</td>
                  <td><TrustBadge level={document.trust_level} /></td>
                  <td>{document.chunks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
