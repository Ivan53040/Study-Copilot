import { useState } from "react";
import { api } from "../api";
import type { DailyPlan, VaultScope } from "../types";
import { CoursePicker } from "../CoursePicker";

const STATUS_COLOR: Record<string, string> = {
  strong: "var(--good)",
  good: "var(--accent)",
  developing: "var(--warn)",
  weak: "var(--danger)",
};

export function PlanPage() {
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [minutes, setMinutes] = useState("60");
  const [examDate, setExamDate] = useState("");
  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (write: boolean) => {
    if (!scope) return;
    setError(null);
    setSavedPath(null);
    setLoading(true);
    try {
      const result = await api.dailyPlan({
        course: scope.course ?? scope.name,
        available_minutes: Number(minutes) || 60,
        exam_date: examDate || null,
        write,
      });
      setPlan(result);
      if (write && result.written) setSavedPath(result.target_path);
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
        Build a plan from weak topics, review history, and exam frequency for any
        course in your vault.
      </p>

      <div className="card">
        <div className="row">
          <div className="grow">
            <div className="small muted">Course</div>
            <CoursePicker value={scope} onChange={setScope} />
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
          <button className="primary" onClick={() => run(false)} disabled={loading || !scope}>
            {loading ? "…" : "Build plan"}
          </button>
          <button onClick={() => run(true)} disabled={loading || !plan || !scope}>
            Save to vault
          </button>
        </div>
      </div>

      {error && <div className="warn-banner" style={{ marginTop: 12 }}>{error}</div>}
      {savedPath && <div className="note-banner" style={{ marginTop: 12 }}>✓ Saved to <code>{savedPath}</code></div>}

      {plan && (
        <div style={{ marginTop: 16 }}>
          {plan.data.days_until_exam != null && (
            <div className="note-banner" style={{ marginBottom: 12 }}>
              Exam in <b>{plan.data.days_until_exam}</b> day(s)
            </div>
          )}
          {plan.data.blocks.length === 0 ? (
            <div className="muted">No weak topics yet — take a quiz for this course to surface gaps.</div>
          ) : (
            <div className="card" style={{ padding: 0 }}>
              <table>
                <thead><tr><th>#</th><th>Concept</th><th>Time</th><th>Focus</th></tr></thead>
                <tbody>
                  {plan.data.blocks.map((block, index) => (
                    <tr key={block.concept_id}>
                      <td>{index + 1}</td>
                      <td><span style={{ color: STATUS_COLOR[block.status] }}>● </span>{block.concept}</td>
                      <td>{block.minutes} min</td>
                      <td className="muted">{block.action}</td>
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
