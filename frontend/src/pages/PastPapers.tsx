import { useState } from "react";
import { api } from "../api";
import type { AnalyzeReport, PastPaperQuestion } from "../types";

export function PastPapersPage() {
  const [course, setCourse] = useState("REIT6811");
  const [report, setReport] = useState<AnalyzeReport | null>(null);
  const [questions, setQuestions] = useState<PastPaperQuestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = async () => {
    setError(null);
    setLoading(true);
    try {
      const r = await api.analyzePastPapers(course || null);
      setReport(r);
      const list = await api.pastPapers(course);
      setQuestions(list.questions);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Frequency per concept, derived from extracted questions.
  const freq = questions.reduce<Record<string, number>>((acc, q) => {
    const k = q.concept ?? "General";
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
  const freqRows = Object.entries(freq).sort((a, b) => b[1] - a[1]);

  return (
    <div>
      <h1 className="page-title">Past Papers</h1>
      <p className="page-sub">
        Extract questions from past papers and estimate which concepts come up
        most — this feeds your study-plan priorities.
      </p>

      <div className="card">
        <div className="row">
          <input value={course} onChange={(e) => setCourse(e.target.value)} style={{ width: 160 }} />
          <button className="primary" onClick={analyze} disabled={loading}>
            {loading ? "Analysing…" : "Analyse past papers"}
          </button>
        </div>
      </div>

      {error && <div className="warn-banner" style={{ marginTop: 12 }}>{error}</div>}

      {report && (
        <div className="note-banner" style={{ marginTop: 12 }}>
          {report.documents} paper(s) · {report.questions} questions ·{" "}
          {report.concepts_updated} concept frequencies updated
          {report.warnings.length > 0 && <> · {report.warnings.join(" ")}</>}
        </div>
      )}

      {freqRows.length > 0 && (
        <div className="card" style={{ padding: 0, marginTop: 16 }}>
          <table>
            <thead>
              <tr>
                <th>Concept</th>
                <th>Exam frequency</th>
              </tr>
            </thead>
            <tbody>
              {freqRows.map(([concept, n]) => (
                <tr key={concept}>
                  <td>{concept}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {questions.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="small muted" style={{ marginBottom: 8 }}>
            Extracted questions
          </div>
          {questions.slice(0, 30).map((q) => (
            <div className="result" key={q.id}>
              <div className="meta">
                <span>{q.concept}</span>
                {q.marks != null && <span>· {q.marks} marks</span>}
              </div>
              <div className="snippet">{q.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
