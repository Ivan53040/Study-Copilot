import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Icon } from "../icons";
import { useScopes } from "../CoursePicker";
import type { Deadline, TodaySummary, TopicPriority } from "../types";
import "../styles/today.css";

export interface QuizRequestFromPage {
  topic: string;
  course: string | null;
  documentIds?: number[];
}

const MINUTE_CHOICES = [30, 60, 90, 120];
const MINUTES_KEY = "sc.today.minutes";

function readMinutes() {
  try {
    const value = Number(localStorage.getItem(MINUTES_KEY));
    return MINUTE_CHOICES.includes(value) ? value : 60;
  } catch {
    return 60;
  }
}

function longDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

function shortDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function countdown(days: number) {
  if (days <= 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days < 14) return `${days} days`;
  const weeks = Math.round(days / 7);
  return `${weeks} weeks`;
}

function urgency(days: number) {
  if (days <= 3) return "urgent";
  if (days <= 14) return "soon";
  return "later";
}

const KIND_LABEL: Record<Deadline["kind"], string> = {
  exam: "Exam",
  assignment: "Assignment",
  other: "Date",
};

function Meter({ value, status }: { value: number; status: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <span className="meter" title={`Confidence ${pct}%`} aria-label={`Confidence ${pct}%`}>
      <span className={`meter-fill s-${status}`} style={{ width: `${Math.max(pct, 4)}%` }} />
    </span>
  );
}

function TopicRow({
  topic,
  onQuiz,
  onAsk,
  quizLabel = "Quiz me",
}: {
  topic: TopicPriority;
  onQuiz: () => void;
  onAsk?: () => void;
  quizLabel?: string;
}) {
  return (
    <div className="today-row">
      <div className="today-row-main">
        <span className="today-row-title">{topic.name}</span>
        <span className="today-row-meta">
          {topic.course && <span>{topic.course}</span>}
          <span className={`status-tag s-${topic.status}`}>{topic.status}</span>
          {topic.exam_frequency > 0 && (
            <span title="Times this concept came up in past papers">
              in {topic.exam_frequency} past {topic.exam_frequency === 1 ? "paper" : "papers"}
            </span>
          )}
        </span>
      </div>
      <Meter value={topic.confidence} status={topic.status} />
      <div className="today-row-actions">
        {onAsk && (
          <button type="button" className="ghost small" onClick={onAsk} title="Ask the chat to explain this">
            <Icon name="message-circle" size={14} /> Ask
          </button>
        )}
        <button type="button" className="small" onClick={onQuiz}>
          <Icon name="graduation-cap" size={14} /> {quizLabel}
        </button>
      </div>
    </div>
  );
}

function AddDeadline({
  courses,
  onAdded,
  onCancel,
}: {
  courses: string[];
  onAdded: () => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [course, setCourse] = useState("");
  const [date, setDate] = useState("");
  const [kind, setKind] = useState<Deadline["kind"]>("exam");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim() || !date) return;
    setSaving(true);
    setError(null);
    try {
      await api.createDeadline({ title: title.trim(), date, course: course.trim() || null, kind });
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="deadline-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <input
        autoFocus
        value={title}
        placeholder="e.g. DECO7250 final exam"
        aria-label="What is due"
        onChange={(event) => setTitle(event.target.value)}
      />
      <div className="deadline-form-row">
        <input
          list="today-courses"
          value={course}
          placeholder="Course"
          aria-label="Course"
          onChange={(event) => setCourse(event.target.value)}
        />
        <datalist id="today-courses">
          {courses.map((code) => (
            <option key={code} value={code} />
          ))}
        </datalist>
        <input type="date" value={date} aria-label="Date" onChange={(event) => setDate(event.target.value)} />
        <select value={kind} aria-label="Kind" onChange={(event) => setKind(event.target.value as Deadline["kind"])}>
          <option value="exam">Exam</option>
          <option value="assignment">Assignment</option>
          <option value="other">Other</option>
        </select>
      </div>
      {error && <div className="warn-banner">{error}</div>}
      <div className="deadline-form-row end">
        <button type="button" className="ghost small" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="primary small" disabled={saving || !title.trim() || !date}>
          {saving ? "Adding…" : "Add date"}
        </button>
      </div>
    </form>
  );
}

export function TodayPage({
  onQuiz,
  onAsk,
  onNavigate,
}: {
  onQuiz: (request: QuizRequestFromPage) => void;
  onAsk: (prompt: string) => void;
  onNavigate: (tab: string) => void;
}) {
  const [summary, setSummary] = useState<TodaySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [minutes, setMinutes] = useState(readMinutes);
  const [course, setCourse] = useState<string>("");
  const [adding, setAdding] = useState(false);
  const scopes = useScopes({ courseOnly: true });

  const courses = useMemo(() => {
    const codes = new Set<string>();
    for (const scope of scopes) if (scope.course) codes.add(scope.course);
    for (const item of summary?.deadlines ?? []) if (item.course) codes.add(item.course);
    return [...codes].sort();
  }, [scopes, summary]);

  const load = useCallback(() => {
    api
      .today({ course: course || null, minutes })
      .then((result) => {
        setSummary(result);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, [course, minutes]);

  useEffect(() => {
    load();
  }, [load]);

  const removeDeadline = async (item: Deadline) => {
    if (!window.confirm(`Remove “${item.title}”?`)) return;
    await api.deleteDeadline(item.id).catch(() => {});
    load();
  };

  const quizTopic = (topic: TopicPriority) => onQuiz({ topic: topic.name, course: topic.course });
  const askTopic = (topic: TopicPriority) =>
    onAsk(`Explain ${topic.name}${topic.course ? ` (${topic.course})` : ""} and what I should know for the exam.`);

  const plan = summary?.plan;
  const nextExam = summary?.deadlines.find((item) => item.kind === "exam");
  const stats = summary?.stats;

  return (
    <div className="today">
      <header className="today-head">
        <div>
          <h1 className="page-title">Today</h1>
          <p className="page-sub">{summary ? longDate(summary.date) : " "}</p>
        </div>
        <label className="today-filter">
          <span className="sr-only">Course</span>
          <select value={course} onChange={(event) => setCourse(event.target.value)}>
            <option value="">All courses</option>
            {courses.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && <div className="warn-banner">{error}</div>}

      {stats && stats.concepts > 0 && (
        <div className="today-stats">
          <span>
            <strong>{stats.concepts}</strong> {stats.concepts === 1 ? "topic" : "topics"} tracked
          </span>
          {stats.average_confidence != null && (
            <span>
              <strong>{Math.round(stats.average_confidence * 100)}%</strong> average confidence
            </span>
          )}
          <span>
            <strong>{stats.answers_this_week}</strong> {stats.answers_this_week === 1 ? "answer" : "answers"} marked this week
          </span>
        </div>
      )}

      <div className="today-grid">
        <section className="today-card" aria-labelledby="today-coming">
          <div className="today-card-head">
            <h2 id="today-coming">
              <Icon name="calendar" size={16} /> Coming up
            </h2>
            {!adding && (
              <button type="button" className="ghost small" onClick={() => setAdding(true)}>
                <Icon name="plus" size={14} /> Add date
              </button>
            )}
          </div>
          {adding && (
            <AddDeadline
              courses={courses}
              onCancel={() => setAdding(false)}
              onAdded={() => {
                setAdding(false);
                load();
              }}
            />
          )}
          {summary && summary.deadlines.length > 0 ? (
            <ul className="deadline-list">
              {summary.deadlines.map((item) => (
                <li key={item.id} className="deadline">
                  <span className={`countdown ${urgency(item.days_until)}`}>{countdown(item.days_until)}</span>
                  <span className="deadline-main">
                    <span className="deadline-title">{item.title}</span>
                    <span className="deadline-meta">
                      {[KIND_LABEL[item.kind], item.course, shortDate(item.date)].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="icon-btn deadline-remove"
                    title="Remove"
                    aria-label={`Remove ${item.title}`}
                    onClick={() => void removeDeadline(item)}
                  >
                    <Icon name="x" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            summary &&
            !adding && (
              <p className="today-empty">
                Add your exam and assignment dates to see a countdown here, and a daily plan that builds up to them.
              </p>
            )
          )}
        </section>

        <section className="today-card" aria-labelledby="today-due">
          <div className="today-card-head">
            <h2 id="today-due">
              <Icon name="rotate-ccw" size={16} /> Due for review
              {summary && summary.due_count > 0 && <span className="count-badge">{summary.due_count}</span>}
            </h2>
          </div>
          {summary && summary.due.length > 0 ? (
            <div className="today-rows">
              {summary.due.map((topic) => (
                <TopicRow key={topic.concept_id} topic={topic} quizLabel="Review" onQuiz={() => quizTopic(topic)} />
              ))}
            </div>
          ) : (
            summary && (
              <p className="today-empty">
                {stats && stats.concepts > 0
                  ? "You're all caught up. Topics come back here when they're due for another look."
                  : "When you take quizzes, topics come back here on a spaced-repetition schedule."}
              </p>
            )
          )}
        </section>

        <section className="today-card" aria-labelledby="today-plan">
          <div className="today-card-head">
            <h2 id="today-plan">
              <Icon name="clock" size={16} /> Plan for today
            </h2>
            <div className="segmented small-seg" role="radiogroup" aria-label="Time available">
              {MINUTE_CHOICES.map((value) => (
                <button
                  type="button"
                  key={value}
                  role="radio"
                  aria-checked={minutes === value}
                  className={minutes === value ? "on" : ""}
                  onClick={() => {
                    setMinutes(value);
                    try {
                      localStorage.setItem(MINUTES_KEY, String(value));
                    } catch {
                      /* ignore */
                    }
                  }}
                >
                  {value < 60 ? `${value}m` : `${value / 60}h`}
                </button>
              ))}
            </div>
          </div>
          {nextExam && plan?.days_until_exam != null && (
            <p className="plan-lead">
              Building up to <strong>{nextExam.title}</strong> — {countdown(plan.days_until_exam).toLowerCase()}
              {plan.days_until_exam > 1 ? " to go" : ""}.
            </p>
          )}
          {plan && plan.blocks.length > 0 ? (
            <ol className="plan-blocks">
              {plan.blocks.map((block, index) => (
                <li key={`${block.concept}-${index}`} className="plan-block">
                  <span className="plan-minutes">{block.minutes} min</span>
                  <span className="plan-main">
                    <span className="plan-concept">{block.concept}</span>
                    <span className="plan-action">{block.action}</span>
                  </span>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => onQuiz({ topic: block.concept, course: plan.course })}
                  >
                    Start
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            summary && (
              <div className="today-empty">
                <p>Nothing to plan yet. Take a quiz and Study Copilot will plan around what you get wrong.</p>
                <button type="button" className="small" onClick={() => onNavigate("quiz")}>
                  <Icon name="graduation-cap" size={14} /> Start a quiz
                </button>
              </div>
            )
          )}
        </section>

        <section className="today-card" aria-labelledby="today-weak">
          <div className="today-card-head">
            <h2 id="today-weak">
              <Icon name="target" size={16} /> Weak topics
            </h2>
            <button type="button" className="ghost small" onClick={() => onNavigate("progress")}>
              All progress
            </button>
          </div>
          {summary && summary.weak.length > 0 ? (
            <div className="today-rows">
              {summary.weak.map((topic) => (
                <TopicRow
                  key={topic.concept_id}
                  topic={topic}
                  onQuiz={() => quizTopic(topic)}
                  onAsk={() => askTopic(topic)}
                />
              ))}
            </div>
          ) : (
            summary && <p className="today-empty">No weak topics right now.</p>
          )}
        </section>
      </div>
    </div>
  );
}
