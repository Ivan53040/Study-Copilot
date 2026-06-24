import { useState } from "react";
import { api } from "../api";
import type { QuizResult, SubmitResult } from "../types";
import { Warnings } from "../components";
import { CoursePicker } from "../CoursePicker";
import type { VaultScope } from "../types";

const OUTCOME_COLOR: Record<string, string> = {
  correct: "var(--good)",
  partial: "var(--warn)",
  incorrect: "var(--danger)",
};

export function QuizPage() {
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [week, setWeek] = useState("");
  const [topic, setTopic] = useState("");
  const [num, setNum] = useState("5");
  const [examMode, setExamMode] = useState(false);
  const [quiz, setQuiz] = useState<QuizResult | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    setError(null);
    setResult(null);
    setAnswers({});
    setQuiz(null);
    setLoading(true);
    try {
      const body = {
        course: scope?.course ?? null,
        scope_path: scope?.path ?? null,
        scope_name: scope?.name ?? null,
        week: week ? Number(week) : null,
        topic: topic || null,
        num_questions: Number(num) || 5,
      };
      const r = examMode
        ? await api.generateExam(body)
        : await api.generateQuiz(body);
      setQuiz(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    if (!quiz?.quiz_id) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload = quiz.questions.map((q) => ({
        question_id: q.id,
        answer: answers[q.id] ?? "",
      }));
      setResult(await api.submitQuiz(quiz.quiz_id, payload));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const resultFor = (qid: number) =>
    result?.results.find((r) => r.question_id === qid);

  return (
    <div>
      <h1 className="page-title">Quiz</h1>
      <p className="page-sub">
        Generate a quiz from your materials, answer it, and get marked — results
        update your concept confidence.
      </p>

      <div className="card">
        <div className="row">
          <div>
            <div className="small muted">Course</div>
            <CoursePicker value={scope} onChange={setScope} />
          </div>
          <div>
            <div className="small muted">Week</div>
            <input value={week} onChange={(e) => setWeek(e.target.value)} placeholder="opt" style={{ width: 70 }} />
          </div>
          <div className="grow">
            <div className="small muted">Topic (optional)</div>
            <input className="grow" style={{ width: "100%" }} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. ethics" />
          </div>
          <div>
            <div className="small muted"># Qs</div>
            <input value={num} onChange={(e) => setNum(e.target.value)} style={{ width: 60 }} />
          </div>
        </div>
        <div className="spacer" />
        <div className="row">
          <button className="primary" onClick={generate} disabled={loading || (!scope && !topic)}>
            {loading ? "Generating…" : examMode ? "Generate mock exam" : "Generate quiz"}
          </button>
          <label className="small muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={examMode} onChange={(e) => setExamMode(e.target.checked)} />
            Exam mode (long-answer, past-paper style)
          </label>
        </div>
      </div>

      {error && <div className="warn-banner" style={{ marginTop: 12 }}>{error}</div>}
      {quiz && <Warnings items={quiz.warnings} />}

      {result && (
        <div className="note-banner" style={{ marginTop: 14 }}>
          Score: <b>{result.score}</b> / {result.total}
        </div>
      )}

      {quiz && quiz.questions.length > 0 && (
        <div style={{ marginTop: 16 }}>
          {quiz.questions.map((q, i) => {
            const r = resultFor(q.id);
            return (
              <div className="result" key={q.id}>
                <div className="meta" style={{ marginBottom: 6 }}>
                  <span>Q{i + 1}</span>
                  <span>·</span>
                  <span>{q.concept}</span>
                  <span>·</span>
                  <span>{q.difficulty}</span>
                  {r && (
                    <span style={{ color: OUTCOME_COLOR[r.outcome], fontWeight: 600 }}>
                      · {r.outcome.toUpperCase()}
                    </span>
                  )}
                </div>
                <div style={{ marginBottom: 8 }}>{q.question}</div>

                {q.type === "mcq" && q.options ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {q.options.map((opt) => (
                      <label key={opt} className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <input
                          type="radio"
                          name={`q${q.id}`}
                          disabled={!!result}
                          checked={answers[q.id] === opt}
                          onChange={() => setAnswers((a) => ({ ...a, [q.id]: opt }))}
                        />
                        {opt}
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea
                    style={{ width: "100%", height: 60 }}
                    disabled={!!result}
                    value={answers[q.id] ?? ""}
                    onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                    placeholder="Your answer…"
                  />
                )}

                {r && (
                  <div className="small" style={{ marginTop: 8 }}>
                    <div><b>Correct answer:</b> {r.correct_answer}</div>
                    {r.explanation && <div className="muted" style={{ marginTop: 4 }}>{r.explanation}</div>}
                    {r.feedback && <div className="muted" style={{ marginTop: 4 }}>Feedback: {r.feedback}</div>}
                  </div>
                )}
              </div>
            );
          })}

          {!result && (
            <button className="primary" onClick={submit} disabled={submitting}>
              {submitting ? "Marking…" : "Submit answers"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
