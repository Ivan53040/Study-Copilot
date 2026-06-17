import { useEffect, useState } from "react";
import { api } from "../api";
import type { CourseSummary, DocumentRow } from "../types";
import { TrustBadge } from "../components";

export function LibraryPage() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .courses()
      .then((r) => {
        setCourses(r.courses);
        if (r.courses[0]) setSelected(r.courses[0].course);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    api
      .documents(selected)
      .then((r) => setDocs(r.documents))
      .catch((e) => setError((e as Error).message));
  }, [selected]);

  return (
    <div>
      <h1 className="page-title">Library</h1>
      <p className="page-sub">Indexed courses and documents.</p>

      {error && <div className="warn-banner">{error}</div>}

      <div className="row" style={{ marginBottom: 16 }}>
        {courses.map((c) => (
          <button
            key={c.course}
            className={selected === c.course ? "primary" : ""}
            onClick={() => setSelected(c.course)}
          >
            {c.course} · {c.documents} docs · {c.chunks} chunks
          </button>
        ))}
      </div>

      {docs.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Week</th>
                <th>Type</th>
                <th>Trust</th>
                <th>Chunks</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td>{d.week ?? "—"}</td>
                  <td className="muted">{d.document_type ?? "—"}</td>
                  <td>
                    <TrustBadge level={d.trust_level} />
                  </td>
                  <td>{d.chunks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
