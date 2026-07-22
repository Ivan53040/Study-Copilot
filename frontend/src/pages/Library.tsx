import { useEffect, useState } from "react";
import { api } from "../api";
import type { DocumentRow, TransformationTemplate, VaultScope } from "../types";
import { TrustBadge } from "../components";
import { CoursePicker } from "../CoursePicker";

export function LibraryPage() {
  const [selected, setSelected] = useState<VaultScope | null>(null);
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [templates, setTemplates] = useState<TransformationTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [setName, setSetName] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .transformationTemplates()
      .then((result) => {
        setTemplates(result.templates);
        setTemplateId(result.templates[0]?.id ?? null);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!selected) return;
    api
      .scopeDocuments(selected.path)
      .then((result) => setDocs(result.documents))
      .catch((e) => setError((e as Error).message));
  }, [selected]);

  const saveStudySet = async () => {
    if (!selected || docs.length === 0) return;
    setError(null);
    setMessage("");
    try {
      const result = await api.saveStudySet({
        name: setName.trim() || selected.name,
        course: selected.course,
        scope_path: selected.kind === "study_set" ? null : selected.path,
        items: docs.map((doc) => ({ kind: "document", ref: doc.id, mode: "snippets" })),
      });
      setSetName("");
      setMessage(`Saved study set "${result.name}".`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const runTransformation = async (document: DocumentRow) => {
    if (!templateId) return;
    setError(null);
    setMessage("");
    try {
      const result = await api.runTransformation({
        template_id: templateId,
        target_kind: "document",
        target_ref: String(document.id),
      });
      setMessage(`Transformation queued as job #${result.job.id}.`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <h1 className="page-title">Library</h1>
      <p className="page-sub">Browse indexed documents from any course or vault folder.</p>
      {error && <div className="warn-banner">{error}</div>}
      <div className="course-toolbar">
        <CoursePicker value={selected} onChange={setSelected} />
        {selected && <span className="muted small">{docs.length} documents</span>}
      </div>
      {selected && docs.length > 0 && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div className="row">
            <input
              value={setName}
              onChange={(event) => setSetName(event.target.value)}
              placeholder={`Study set name (${selected.name})`}
            />
            <button onClick={saveStudySet}>Save scope as study set</button>
            <select
              value={templateId ?? ""}
              onChange={(event) => setTemplateId(Number(event.target.value))}
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      {message && <div className="note-banner">{message}</div>}
      {selected && docs.length === 0 && <div className="note-banner">No indexed documents in this scope.</div>}
      {docs.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Title</th><th>Week</th><th>Type</th><th>Trust</th><th>Chunks</th><th></th></tr></thead>
            <tbody>
              {docs.map((document) => (
                <tr key={document.id}>
                  <td>{document.title}</td>
                  <td>{document.week ?? "—"}</td>
                  <td className="muted">{document.document_type ?? "—"}</td>
                  <td><TrustBadge level={document.trust_level} /></td>
                  <td>{document.chunks}</td>
                  <td>
                    <button
                      className="small"
                      onClick={() => runTransformation(document)}
                      disabled={!templateId}
                    >
                      Transform
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
