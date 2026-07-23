import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Icon } from "../icons";
import type {
  AppSettings,
  LectureDocument,
  LecturePreview,
  LectureViewer,
  TransformationTemplate,
} from "../types";

export function LecturesPage() {
  const [documents, setDocuments] = useState<LectureDocument[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [selectedCourse, setSelectedCourse] = useState<string | null>(null);
  const [selected, setSelected] = useState<LecturePreview | null>(null);
  const [templates, setTemplates] = useState<TransformationTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [viewer, setViewer] = useState<LectureViewer | null>(null);
  const [viewerPath, setViewerPath] = useState("");
  const [viewerPage, setViewerPage] = useState(1);
  const [viewerZoom, setViewerZoom] = useState(1);
  const [viewerBusy, setViewerBusy] = useState(false);
  const [viewerError, setViewerError] = useState("");

  const load = useCallback(async () => {
    const [result, appSettings] = await Promise.all([
      api.lectureMaterials(),
      api.settings(),
    ]);
    setDocuments(result.documents);
    setSettings(appSettings);
    api
      .transformationTemplates()
      .then((templateResult) => {
        setTemplates(templateResult.templates);
        setTemplateId(templateResult.templates[0]?.id ?? null);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    load().catch((error) => setMessage((error as Error).message));
  }, [load]);

  // Group documents by course — prefer the folder name (immediate subfolder under
  // the lecture root) so Year1Sem1/CSSE7030/file.pdf → "CSSE7030" reliably.
  const courses = useMemo(() => {
    const map = new Map<string, LectureDocument[]>();
    for (const doc of documents) {
      const key = doc.folder_course ?? doc.course ?? "Unclassified";
      const list = map.get(key) ?? [];
      list.push(doc);
      map.set(key, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) =>
      a === "Unclassified" ? 1 : b === "Unclassified" ? -1 : a.localeCompare(b),
    );
  }, [documents]);

  const filteredCourses = useMemo(() => {
    if (!query) return courses;
    const q = query.toLowerCase();
    return courses
      .map(([course, docs]) => [
        course,
        docs.filter((d) =>
          `${d.title} ${d.relative_path} ${d.folder_course ?? d.course ?? ""}`.toLowerCase().includes(q),
        ),
      ] as [string, LectureDocument[]])
      .filter(([, docs]) => docs.length > 0);
  }, [courses, query]);

  const courseFiles = useMemo(
    () => courses.find(([c]) => c === selectedCourse)?.[1] ?? [],
    [courses, selectedCourse],
  );

  const selectCourse = (course: string) => {
    setSelectedCourse(course);
    setSelected(null);
  };

  const selectFile = (doc: LectureDocument) => {
    api
      .lectureMaterial(doc.id)
      .then(setSelected)
      .catch((error) => setMessage((error as Error).message));
  };

  const openViewer = async (doc: LectureDocument) => {
    setViewerBusy(true);
    setViewerError("");
    setViewerPath(doc.path);
    setViewerPage(1);
    setViewerZoom(1);
    try {
      setViewer(await api.lectureViewer(doc.id));
    } catch (error) {
      setViewerError((error as Error).message);
    } finally {
      setViewerBusy(false);
    }
  };

  const runTransformation = async () => {
    if (!selected || !templateId) return;
    setMessage("");
    try {
      const result = await api.runTransformation({
        template_id: templateId,
        target_kind: "document",
        target_ref: String(selected.id),
      });
      setMessage(`Transformation queued as job #${result.job.id}.`);
    } catch (error) {
      setMessage((error as Error).message);
    }
  };

  const closeViewer = useCallback(() => {
    setViewer(null);
    setViewerPath("");
    setViewerError("");
    setViewerBusy(false);
  }, []);

  useEffect(() => {
    if (!viewer && !viewerBusy && !viewerError) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeViewer();
      if (!viewer) return;
      if (event.key === "ArrowLeft") setViewerPage((page) => Math.max(1, page - 1));
      if (event.key === "ArrowRight") {
        setViewerPage((page) => Math.min(viewer.pages, page + 1));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeViewer, viewer, viewerBusy, viewerError]);

  const chooseFolder = async () => {
    if (!("__TAURI_INTERNALS__" in window)) {
      setMessage("Folder browsing is available in the desktop app.");
      return;
    }
    if (!settings) return;
    setBusy(true);
    setMessage("");
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const folder = await open({
        multiple: false,
        directory: true,
        title: "Choose your Lecture Notes folder",
      });
      if (!folder || typeof folder !== "string") return;
      const result = await api.saveSettings({
        ...settings,
        lectures_root: folder,
      });
      setSettings(result.settings);
      const scan = await api.scanVault();
      await load();
      setMessage(`Lecture folder set. Indexed ${scan.new + scan.updated} files.`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const scanFolder = async () => {
    setBusy(true);
    setMessage("");
    try {
      const scan = await api.scanVault();
      await load();
      const total = scan.new + scan.updated;
      setMessage(
        total > 0
          ? `Scanned: ${scan.new} new, ${scan.updated} updated, ${scan.unchanged} unchanged.`
          : `Nothing new found. (${scan.unchanged} files already indexed)`,
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const importMaterials = async () => {
    if (!("__TAURI_INTERNALS__" in window)) {
      setMessage("File browsing is available in the desktop app.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const folder = await open({
        multiple: false,
        directory: true,
        title: "Select a folder of lecture notes (PDF / PowerPoint)",
      });
      if (!folder || typeof folder !== "string") return;
      const imported = await api.importLectureFolder(folder);
      const scan = await api.scanVault();
      await load();
      setMessage(
        `Imported ${imported.count} file${imported.count === 1 ? "" : "s"} from folder; indexed ${scan.new + scan.updated}.`,
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const lectureFolder = settings?.lectures_root ?? null;

  return (
    <div className="lectures-page">
      <div className="lectures-header">
        <div>
          <h1 className="page-title">Lecture Materials</h1>

          <p className="page-sub">
            PDFs and PowerPoint slides indexed for Search, Chat, Generate, Quiz, and Plan.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={scanFolder} disabled={busy}>
            <Icon name="refresh-cw" size={15} /> {busy ? "Scanning…" : "Scan folder"}
          </button>
          <button className="primary" onClick={importMaterials} disabled={busy}>
            <Icon name="upload" size={15} /> {busy ? "Importing…" : "Add materials"}
          </button>
        </div>
      </div>

      {/* Folder path row */}
      <div className="lecture-folder-row">
        <Icon name="folder" size={14} />
        <span className="lecture-folder-path">
          {lectureFolder ?? <span className="muted">vault/Lecture Materials (default)</span>}
        </span>
        <button onClick={chooseFolder} disabled={busy} className="small">
          {lectureFolder ? "Change folder" : "Choose folder…"}
        </button>
      </div>

      {message && <div className="note-banner">{message}</div>}
      <div className="lectures-layout">
        {/* Left: course list */}
        <aside className="lecture-list card">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search courses or files…"
          />
          <div className="lecture-count">
            {courses.length} course{courses.length !== 1 ? "s" : ""} · {documents.length} files
          </div>
          {filteredCourses.map(([course, docs]) => (
            <button
              key={course}
              className={`lecture-item ${selectedCourse === course ? "active" : ""}`}
              onClick={() => selectCourse(course)}
            >
              <Icon name="book" size={15} />
              <span>
                <strong>{course}</strong>
                <small>{docs.length} file{docs.length !== 1 ? "s" : ""}</small>
              </span>
            </button>
          ))}
          {!filteredCourses.length && (
            <div className="muted small">No lecture materials yet.</div>
          )}
        </aside>

        {/* Right: file list + preview */}
        <section className="lecture-preview card">
          {selectedCourse ? (
            <>
              <div className="lecture-preview-header">
                <div>
                  <h2>{selectedCourse}</h2>
                  <div className="muted small">{courseFiles.length} file{courseFiles.length !== 1 ? "s" : ""}</div>
                </div>
              </div>
              <div className="lecture-course-files">
                {courseFiles.map((doc) => (
                  <button
                    key={doc.id}
                    className={`lecture-file-item ${selected?.id === doc.id ? "active" : ""}`}
                    title="Double-click to open document viewer"
                    onClick={() => selectFile(doc)}
                    onDoubleClick={() => void openViewer(doc)}
                  >
                    <Icon name={doc.extension === ".pdf" ? "file-text" : "layers"} size={14} />
                    <span className="lecture-file-title">{doc.title}</span>
                    <span className="lecture-file-meta">{doc.extension.replace(".", "").toUpperCase()} · {doc.chunks} chunks</span>
                  </button>
                ))}
              </div>
              {selected && courseFiles.some((d) => d.id === selected.id) && (
                <div className="lecture-sections">
                  <div className="lecture-file-detail-header">
                    <span>{selected.title}</span>
                    <select
                      value={templateId ?? ""}
                      onChange={(event) => setTemplateId(Number(event.target.value))}
                    >
                      {templates.map((template) => (
                        <option key={template.id} value={template.id}>
                          {template.name}
                        </option>
                      ))}
                    </select>
                    <button className="small" onClick={runTransformation} disabled={!templateId}>
                      Transform
                    </button>
                    <button className="small" onClick={() => api.vaultOpenExternal(selected.path)}>
                      <Icon name="external-link" size={13} /> Open
                    </button>
                  </div>
                  {selected.sections.map((section, i) => (
                    <article key={`${section.page}-${i}`}>
                      <h3>{section.heading || (section.page ? `Page / slide ${section.page}` : `Section ${i + 1}`)}</h3>
                      <p>{section.content}</p>
                    </article>
                  ))}
                  {!selected.sections.length && (
                    <div className="muted">No extractable text was found in this file.</div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="lecture-empty">
              <Icon name="book" size={38} />
              <p>Select a course on the left to see its lecture files.</p>
              {!lectureFolder && (
                <button onClick={chooseFolder} disabled={busy}>
                  <Icon name="folder" size={14} /> Choose lecture folder…
                </button>
              )}
            </div>
          )}
        </section>
      </div>
      {(viewer || viewerBusy || viewerError) && (
        <div className="lecture-viewer-backdrop" onMouseDown={closeViewer}>
          <section
            className="lecture-viewer"
            onMouseDown={(event) => event.stopPropagation()}
            aria-label="Lecture document viewer"
          >
            <header className="lecture-viewer-toolbar">
              <div className="lecture-viewer-title">
                <Icon name={viewer?.extension === ".pdf" ? "file-text" : "layers"} size={17} />
                <span>{viewer?.title ?? "Opening document…"}</span>
              </div>
              {viewer && (
                <>
                  <button
                    className="small"
                    disabled={viewerPage <= 1}
                    onClick={() => setViewerPage((page) => Math.max(1, page - 1))}
                    aria-label="Previous page"
                  >
                    ‹
                  </button>
                  <span className="lecture-viewer-page-count">
                    {viewerPage} / {viewer.pages}
                  </span>
                  <button
                    className="small"
                    disabled={viewerPage >= viewer.pages}
                    onClick={() => setViewerPage((page) => Math.min(viewer.pages, page + 1))}
                    aria-label="Next page"
                  >
                    ›
                  </button>
                  <button
                    className="small"
                    onClick={() => setViewerZoom((zoom) => Math.max(0.6, zoom - 0.15))}
                    aria-label="Zoom out"
                  >
                    −
                  </button>
                  <span className="lecture-viewer-zoom">{Math.round(viewerZoom * 100)}%</span>
                  <button
                    className="small"
                    onClick={() => setViewerZoom((zoom) => Math.min(2, zoom + 0.15))}
                    aria-label="Zoom in"
                  >
                    +
                  </button>
                  <button className="small" onClick={() => api.vaultOpenExternal(viewerPath)}>
                    <Icon name="external-link" size={13} /> Open
                  </button>
                </>
              )}
              <button className="small lecture-viewer-close" onClick={closeViewer} aria-label="Close viewer">
                ×
              </button>
            </header>
            <div className="lecture-viewer-canvas">
              {viewerBusy && <div className="lecture-viewer-status">Preparing document preview…</div>}
              {viewerError && (
                <div className="lecture-viewer-status error">
                  <p>{viewerError}</p>
                  <button onClick={() => api.vaultOpenExternal(viewerPath)}>
                    <Icon name="external-link" size={14} /> Open in desktop app
                  </button>
                </div>
              )}
              {viewer && (
                <img
                  key={`${viewer.id}-${viewerPage}-${viewerZoom}`}
                  src={api.lectureViewerPageUrl(
                    viewer.id,
                    viewerPage,
                    Math.min(3, Math.max(1.25, viewerZoom * 1.6)),
                  )}
                  alt={`${viewer.title}, ${viewer.extension === ".pdf" ? "page" : "slide"} ${viewerPage}`}
                  style={{ width: `${viewerZoom * 100}%` }}
                />
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
