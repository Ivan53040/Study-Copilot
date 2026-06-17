import { useState } from "react";
import { api } from "../api";
import type { DailyPlan } from "../types";

const STATUS_COLOR: Record<string, string> = {
  strong: "var(--good)",
  good: "var(--accent)",
  developing: "var(--warn)",
  weak: "var(--danger)",
};

export function PlanPage() {
  const [course, setCourse] = useState("REIT6811");
  const [minutes, setMinutes] = useState("60");
  const [examDate, setExamDate] = useState("");
  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (write: boolean) => {
    setError(null);
    setSavedPath(null);
    setLoading(true);
    try {
      const p = await api.dailyPlan({
        course: course || null,
        available_minutes: Number(minutes) || 60,
        exam_date: examDate || null,
        write,
      });
      setPlan(p);
      if (write && p.written) setSavedPath(p.target_path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">Daily Plan</h1>
      <p className="page-sub">
        A prioritised study plan from your weak topics, review schedule, and exam
        frequency.
      </p>

      <div className="card">
        <div className="row">
          <div>
            <div className="small muted">Course</div>
            <input value={course} onChange={(e) => setCourse(e.target.value)} />
          </div>
          <div>
            <div className="small muted">Available minutes</div>
            <input value={minutes} onChange={(e) => setMinutes(e.target.value)} style={{ width: 110 }} />
          </div>
          <div>
            <div className="small muted">Exam date (optional)</div>
            <input type="date" value={examDate} onChange={(e) => setExamDate(e.target.value)} />
          </div>
        </div>
        <div className="spacer" />
        <div className="row">
          <button className="primary" onClick={() => run(false)} disabled={loading}>
            {loading ? "…" : "Build plan"}
          </button>
          <button onClick={() => run(true)} disabled={loading || !plan}>
            Save to vault
          </button>
        </div>
      </div>

      {error && <div className="warn-banner" style={{ marginTop: 12 }}>{error}</div>}
      {savedPath && (
        <div className="note-banner" style={{ marginTop: 12 }}>
          ✓ Saved to <code>{savedPath}</code>
        </div>
      )}

      {plan && (
        <div style={{ marginTop: 16 }}>
          {plan.data.days_until_exam != null && (
            <div className="note-banner" style={{ marginBottom: 12 }}>
              Exam in <b>{plan.data.days_until_exam}</b> day(s)
            </div>
          )}
          {plan.data.blocks.length === 0 ? (
            <div className="muted">
              No weak topics to plan — take a quiz to surface gaps.
            </div>
          ) : (
            <div className="card" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Concept</th>
                    <th>Time</th>
                    <th>Focus</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.data.blocks.map((b, i) => (
                    <tr key={b.concept_id}>
                      <td>{i + 1}</td>
                      <td>
                        <span style={{ color: STATUS_COLOR[b.status] }}>● </span>
                        {b.concept}
                      </td>
                      <td>{b.minutes} min</td>
                      <td className="muted">{b.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
