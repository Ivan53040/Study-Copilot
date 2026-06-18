import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import type { NotePreview } from "../types";
import { Warnings } from "../components";

export function GeneratePage() {
  const [course, setCourse] = useState("REIT6811");
  const [week, setWeek] = useState("");
  const [topic, setTopic] = useState("");
  const [preview, setPreview] = useState<NotePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const body = () => ({
    course: course || null,
    week: week ? Number(week) : null,
    topic: topic || null,
  });

  const generate = async () => {
    setError(null);
    setSavedPath(null);
    setLoading(true);
    try {
      setPreview(await api.generateNote({ ...body(), write: false }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const res = await api.generateNote({ ...body(), write: true });
      setPreview(res);
      setSavedPath(res.target_path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">Generate Notes</h1>
      <p className="page-sub">
        Source-grounded revision notes. Preview first; saving writes only into
        <code> StudyCopilot/Generated Notes/</code>.
      </p>

      <div className="card">
        <div className="row">
          <div>
            <div className="small muted">Course</div>
            <input value={course} onChange={(e) => setCourse(e.target.value)} />
          </div>
          <div>
            <div className="small muted">Week (optional)</div>
            <input
              value={week}
              onChange={(e) => setWeek(e.target.value)}
              placeholder="e.g. 5"
              style={{ width: 90 }}
            />
          </div>
          <div className="grow">
            <div className="small muted">Topic (optional)</div>
            <input
              className="grow"
              style={{ width: "100%" }}
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. informed consent"
            />
          </div>
        </div>
        <div className="spacer" />
        <div className="row">
          <button className="primary" onClick={generate} disabled={loading}>
            {loading ? "Generating…" : "Preview"}
          </button>
          <button onClick={save} disabled={saving || !preview}>
            {saving ? "Saving…" : "Save to vault"}
          </button>
        </div>
      </div>

      {error && <div className="warn-banner" style={{ marginTop: 12 }}>{error}</div>}

      {savedPath && (
        <div className="note-banner" style={{ marginTop: 12 }}>
          ✓ Saved to <code>{savedPath}</code> — it will sync to iCloud shortly.
        </div>
      )}

      {preview && (
        <>
          <Warnings items={preview.warnings} />
          {preview.content ? (
            <div className="preview">
              <div className="muted small" style={{ marginBottom: 8 }}>
                {preview.title} → <code>{preview.target_path}</code>
              </div>
              <div className="md">
                <ReactMarkdown>{preview.content}</ReactMarkdown>
              </div>
            </div>
          ) : (
            <div className="muted" style={{ marginTop: 12 }}>
              No content generated.
            </div>
          )}
        </>
      )}
    </div>
  );
}
