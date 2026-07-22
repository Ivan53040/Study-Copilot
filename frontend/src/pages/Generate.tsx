import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";
import { api } from "../api";
import type { Job, NotePreview, TransformationTemplate } from "../types";
import { Warnings } from "../components";
import { CoursePicker } from "../CoursePicker";
import type { VaultScope } from "../types";

export function GeneratePage() {
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [week, setWeek] = useState("");
  const [topic, setTopic] = useState("");
  const [preview, setPreview] = useState<NotePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [templates, setTemplates] = useState<TransformationTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [transformJob, setTransformJob] = useState<Job | null>(null);
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
    if (!transformJob || !["queued", "running"].includes(transformJob.status)) return;
    const timer = window.setTimeout(() => {
      api.job(transformJob.id).then(setTransformJob).catch((e) => setError((e as Error).message));
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [transformJob]);

  const body = () => ({
    course: scope?.course ?? null,
    scope_path: scope?.kind === "study_set" ? null : scope?.path ?? null,
    scope_name: scope?.name ?? null,
    study_set_id: scope?.study_set_id ?? null,
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

  const runTransformation = async () => {
    if (!templateId || scope?.kind !== "study_set") return;
    setError(null);
    try {
      const result = await api.runTransformation({
        template_id: templateId,
        target_kind: "study_set",
        study_set_id: scope.study_set_id ?? null,
      });
      setTransformJob(result.job);
    } catch (e) {
      setError((e as Error).message);
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
            <CoursePicker value={scope} onChange={setScope} />
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
          <button className="primary" onClick={generate} disabled={loading || (!scope && !topic)}>
            {loading ? "Generating…" : "Preview"}
          </button>
          <button onClick={save} disabled={saving || !preview}>
            {saving ? "Saving…" : "Save to vault"}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="row">
          <div className="grow">
            <div className="small muted">Reusable transformation</div>
            <select
              style={{ width: "100%" }}
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
          <button
            onClick={runTransformation}
            disabled={!templateId || scope?.kind !== "study_set"}
          >
            Run transformation
          </button>
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>
          Select a saved study set to transform a reusable scope.
        </div>
        {transformJob && (
          <div className="note-banner" style={{ marginTop: 10 }}>
            Job #{transformJob.id}: {transformJob.status}
            {transformJob.message ? ` - ${transformJob.message}` : ""}
            {transformJob.result?.output_path
              ? ` - saved to ${String(transformJob.result.output_path)}`
              : ""}
          </div>
        )}
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
                <ReactMarkdown
                  remarkPlugins={mdRemarkPlugins}
                  rehypePlugins={mdRehypePlugins}
                  components={mdComponents}
                >
                  {preview.content}
                </ReactMarkdown>
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
