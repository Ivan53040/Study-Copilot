import { useEffect, useState } from "react";
import { api } from "../api";
import type { ConceptProgress } from "../types";

const STATUS_COLOR: Record<string, string> = {
  strong: "var(--good)",
  good: "var(--accent)",
  developing: "var(--warn)",
  weak: "var(--danger)",
};

function ConfidenceBar({ value, status }: { value: number; status: string }) {
  return (
    <div style={{ background: "var(--panel-2)", borderRadius: 6, height: 10, width: 160, overflow: "hidden" }}>
      <div
        style={{
          width: `${Math.round(value * 100)}%`,
          height: "100%",
          background: STATUS_COLOR[status] ?? "var(--muted)",
        }}
      />
    </div>
  );
}

export function ProgressPage() {
  const [course, setCourse] = useState("REIT6811");
  const [rows, setRows] = useState<ConceptProgress[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setError(null);
    setLoading(true);
    try {
      const r = await api.progress(course);
      setRows(r.concepts);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleDateString() : "—");

  return (
    <div>
      <h1 className="page-title">Progress</h1>
      <p className="page-sub">
        Concept-level confidence from your quiz history, with review scheduling.
      </p>

      <div className="row" style={{ marginBottom: 16 }}>
        <input value={course} onChange={(e) => setCourse(e.target.value)} style={{ width: 160 }} />
        <button className="primary" onClick={load} disabled={loading}>
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      {error && <div className="warn-banner">{error}</div>}

      {rows.length === 0 ? (
        <div className="muted">
          No concept data yet. Take a quiz to start tracking confidence.
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Concept</th>
                <th>Confidence</th>
                <th>Status</th>
                <th>✓ / ✗ / ~</th>
                <th>Next review</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.concept_id}>
                  <td>{c.name}</td>
                  <td>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <ConfidenceBar value={c.confidence} status={c.status} />
                      <span className="small muted">{Math.round(c.confidence * 100)}%</span>
                    </div>
                  </td>
                  <td style={{ color: STATUS_COLOR[c.status], fontWeight: 600 }}>{c.status}</td>
                  <td className="small">
                    {c.correct} / {c.incorrect} / {c.partial}
                  </td>
                  <td className="small muted">{fmtDate(c.next_review)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
