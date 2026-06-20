import { useState } from "react";
import { api } from "../api";
import type { AnalyzeReport, PastPaperQuestion, VaultScope } from "../types";
import { CoursePicker } from "../CoursePicker";

export function PastPapersPage() {
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [report, setReport] = useState<AnalyzeReport | null>(null);
  const [questions, setQuestions] = useState<PastPaperQuestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = async () => {
    if (!scope?.course) return;
    setError(null);
    setLoading(true);
    try {
      const result = await api.analyzePastPapers(scope.course);
      setReport(result);
      const list = await api.pastPapers(scope.course);
      setQuestions(list.questions);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const frequencies = questions.reduce<Record<string, number>>((acc, question) => {
    const key = question.concept ?? "General";
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
  const frequencyRows = Object.entries(frequencies).sort((a, b) => b[1] - a[1]);

  return (
    <div>
      <h1 className="page-title">Past Papers</h1>
      <p className="page-sub">
        Select any course folder, extract its past-paper questions, and feed those
        priorities into your study plan.
      </p>

      <div className="card">
        <div className="row">
          <CoursePicker value={scope} onChange={setScope} courseOnly />
          <button className="primary" onClick={analyze} disabled={loading || !scope?.course}>
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

      {frequencyRows.length > 0 && (
        <div className="card" style={{ padding: 0, marginTop: 16 }}>
          <table>
            <thead><tr><th>Concept</th><th>Exam frequency</th></tr></thead>
            <tbody>
              {frequencyRows.map(([concept, count]) => (
                <tr key={concept}><td>{concept}</td><td>{count}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {questions.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="small muted" style={{ marginBottom: 8 }}>Extracted questions</div>
          {questions.slice(0, 30).map((question) => (
            <div className="result" key={question.id}>
              <div className="meta">
                <span>{question.concept}</span>
                {question.marks != null && <span>· {question.marks} marks</span>}
              </div>
              <div className="snippet">{question.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
