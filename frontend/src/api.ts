import type {
  AnalyzeReport,
  AppSettings,
  BacklinkSearchResponse,
  ChatResponse,
  ConceptProgress,
  CourseSummary,
  DailyPlan,
  DocumentRow,
  Health,
  Job,
  LectureDocument,
  LecturePreview,
  LectureViewer,
  FormatPreview,
  NoteMentions,
  NotePreview,
  NoteTranslation,
  NoteVersion,
  OrganizerMove,
  OrganizerPreview,
  PastPaperQuestion,
  QuizResult,
  SearchResponse,
  SettingsPayload,
  StudySet,
  StudySetItem,
  SubmitResult,
  TranslatedNoteResult,
  TransformationTemplate,
  TreeNode,
  VaultScope,
  VaultGraph,
  VaultNote,
  VoiceNoteResult,
  VoiceNoteStatus,
  VoiceTranscriptionResult,
  WikiGraph,
  WikiPagesResponse,
} from "./types";

// Calls go through the Vite proxy (/api -> backend). Override with VITE_API_BASE.
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // The packaged app spawns the backend at launch, so the first calls may hit a
  // not-yet-listening server. Retry connection failures (not HTTP errors).
  let lastErr: unknown;
  for (let attempt = 0; attempt < 8; attempt++) {
    let res: Response;
    try {
      res = await fetch(`${BASE}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...init,
      });
    } catch (e) {
      lastErr = e; // network error (backend not up yet) -> retry
      await sleep(700);
      continue;
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail ?? JSON.stringify(body);
      } catch {
        /* ignore */
      }
      throw new Error(`${res.status}: ${detail}`);
    }
    return res.json() as Promise<T>;
  }
  throw new Error(`Cannot reach backend: ${(lastErr as Error)?.message ?? "network error"}`);
}

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < 8; attempt++) {
    let res: Response;
    try {
      res = await fetch(`${BASE}${path}`, {
        method: "POST",
        body: form,
      });
    } catch (e) {
      lastErr = e;
      await sleep(700);
      continue;
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail ?? JSON.stringify(body);
      } catch {
        /* ignore */
      }
      throw new Error(`${res.status}: ${detail}`);
    }
    return res.json() as Promise<T>;
  }
  throw new Error(`Cannot reach backend: ${(lastErr as Error)?.message ?? "network error"}`);
}

export const api = {
  health: () => request<Health>("/health"),

  settings: () => request<AppSettings>("/settings"),

  saveSettings: (body: SettingsPayload) =>
    request<{ saved: boolean; settings: AppSettings }>("/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  testLlm: (base_url: string, model: string) =>
    request<{
      connected: boolean;
      model_available: boolean | null;
      models: string[];
    }>("/settings/test-llm", {
      method: "POST",
      body: JSON.stringify({ base_url, model }),
    }),

  courses: () => request<{ courses: CourseSummary[] }>("/courses"),
  scopes: () => request<{ scopes: VaultScope[] }>("/scopes"),

  studySets: () => request<{ study_sets: StudySet[] }>("/study-sets"),

  saveStudySet: (body: {
    name: string;
    course?: string | null;
    scope_path?: string | null;
    items: StudySetItem[];
  }, id?: number) =>
    request<StudySet>(id ? `/study-sets/${id}` : "/study-sets", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(body),
    }),

  deleteStudySet: (id: number) =>
    request<{ deleted: number }>(`/study-sets/${id}`, { method: "DELETE" }),

  jobs: () => request<{ jobs: Job[] }>("/jobs"),

  job: (id: number) => request<Job>(`/jobs/${id}`),

  createJob: (type: string, payload: Record<string, unknown> = {}) =>
    request<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({ type, payload }),
    }),

  scanVault: () =>
    request<{
      new: number;
      updated: number;
      unchanged: number;
      deleted: number;
      chunks: number;
      errors: string[];
    }>("/ingest/scan", {
      method: "POST",
      body: JSON.stringify({ course: null }),
    }),

  lectureMaterials: () =>
    request<{ count: number; documents: LectureDocument[] }>("/lecture-materials"),

  lectureMaterial: (id: number) =>
    request<LecturePreview>(`/lecture-materials/${id}`),

  lectureViewer: (id: number) =>
    request<LectureViewer>(`/lecture-materials/${id}/viewer`),

  lectureViewerPageUrl: (id: number, page: number, scale: number) =>
    `${BASE}/lecture-materials/${id}/viewer/pages/${page}?scale=${scale}`,

  importLectureFolder: (folder_path: string) =>
    request<{ count: number; paths: string[] }>("/lecture-materials/import-folder", {
      method: "POST",
      body: JSON.stringify({ folder_path }),
    }),

  documents: (course: string) =>
    request<{ course: string; count: number; documents: DocumentRow[] }>(
      `/courses/${encodeURIComponent(course)}/documents`,
    ),

  scopeDocuments: (path: string) =>
    request<{ path: string; count: number; documents: DocumentRow[] }>(
      `/scope-documents?path=${encodeURIComponent(path)}`,
    ),

  search: (body: {
    query: string;
    course?: string | null;
    scope_path?: string | null;
    study_set_id?: number | null;
    source_type?: string | null;
    max_trust_level?: number | null;
    week?: number | null;
    limit?: number;
    include_content?: boolean;
  }) =>
    request<SearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  chat: (body: {
    message: string;
    course?: string | null;
    scope_path?: string | null;
    study_set_id?: number | null;
    context_mode?: "retrieval" | "manual" | "hybrid";
    context_items?: StudySetItem[];
    conversation_id?: number | null;
  }) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generateNote: (body: {
    course?: string | null;
    scope_path?: string | null;
    scope_name?: string | null;
    study_set_id?: number | null;
    week?: number | null;
    topic?: string | null;
    write?: boolean;
  }) =>
    request<NotePreview>("/notes/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  voiceNoteStatus: () => request<VoiceNoteStatus>("/voice-notes/status"),

  transcribeVoiceNote: (body: {
    audio: Blob;
    filename: string;
  }) => {
    const form = new FormData();
    form.append("audio", body.audio, body.filename);
    return requestForm<VoiceTranscriptionResult>("/voice-notes/transcribe", form);
  },

  generateVoiceNoteFromTranscript: (body: {
    transcript: string;
    title?: string | null;
    course?: string | null;
    folder?: string | null;
    write?: boolean;
  }) =>
    request<VoiceNoteResult>("/voice-notes/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  createVoiceNote: (body: {
    audio: Blob;
    filename: string;
    title?: string | null;
    course?: string | null;
    folder?: string | null;
    write?: boolean;
  }) => {
    const form = new FormData();
    form.append("audio", body.audio, body.filename);
    if (body.title) form.append("title", body.title);
    if (body.course) form.append("course", body.course);
    if (body.folder) form.append("folder", body.folder);
    form.append("write", String(body.write ?? true));
    return requestForm<VoiceNoteResult>("/voice-notes", form);
  },

  translateNoteText: (body: { text: string; context?: string | null }) =>
    request<NoteTranslation>("/notes/translate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  translateWholeNote: (path: string, background = true) =>
    request<TranslatedNoteResult>("/notes/translate-note", {
      method: "POST",
      body: JSON.stringify({ path, background }),
    }),

  generateQuiz: (body: {
    course?: string | null;
    scope_path?: string | null;
    scope_name?: string | null;
    study_set_id?: number | null;
    week?: number | null;
    topic?: string | null;
    num_questions?: number;
  }) =>
    request<QuizResult>("/quizzes/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  submitQuiz: (quizId: number, answers: { question_id: number; answer: string }[]) =>
    request<SubmitResult>(`/quizzes/${quizId}/submit`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  progress: (course: string) =>
    request<{ course: string; concepts: ConceptProgress[] }>(
      `/progress/${encodeURIComponent(course)}`,
    ),

  dailyPlan: (body: {
    course?: string | null;
    study_set_id?: number | null;
    available_minutes?: number;
    exam_date?: string | null;
    write?: boolean;
  }) =>
    request<DailyPlan>("/plans/daily", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  analyzePastPapers: (course: string | null) =>
    request<AnalyzeReport>("/past-papers/analyze", {
      method: "POST",
      body: JSON.stringify({ course }),
    }),

  pastPapers: (course: string) =>
    request<{ course: string; count: number; questions: PastPaperQuestion[] }>(
      `/past-papers/${encodeURIComponent(course)}`,
    ),

  generateExam: (body: {
    course?: string | null;
    scope_path?: string | null;
    scope_name?: string | null;
    study_set_id?: number | null;
    week?: number | null;
    topic?: string | null;
    num_questions?: number;
  }) =>
    request<QuizResult>("/exams/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  vaultTree: () => request<TreeNode>("/vault/tree"),

  organizerPreview: () =>
    request<OrganizerPreview>("/vault/organize/preview", { method: "POST" }),

  organizerApply: (moves: OrganizerMove[]) =>
    request<{ applied: number; moves: OrganizerMove[]; manifest?: string }>(
      "/vault/organize/apply",
      {
        method: "POST",
        body: JSON.stringify({
          moves: moves.map((move) => ({
            from_path: move.from,
            to_path: move.to,
            reason: move.reason,
          })),
        }),
      },
    ),

  vaultNote: (path: string) =>
    request<VaultNote>(`/vault/note?path=${encodeURIComponent(path)}`),

  vaultSaveNote: (path: string, content: string) =>
    request<{ path: string; written: boolean; backup: string | null }>(
      "/vault/note",
      { method: "PUT", body: JSON.stringify({ path, content }) },
    ),

  vaultCreateFolder: (path: string) =>
    request<{ path: string; created: boolean }>("/vault/folder", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  formatPreview: (path: string, content?: string) =>
    request<FormatPreview>("/vault/format/preview", {
      method: "POST",
      body: JSON.stringify({ path, content }),
    }),

  vaultGraph: () => request<VaultGraph>("/vault/graph"),

  vaultBacklinks: (path: string, aliases: string[] = []) => {
    const params = new URLSearchParams({ path });
    aliases.filter(Boolean).forEach((alias) => params.append("alias", alias));
    return request<NoteMentions>(`/vault/backlinks?${params.toString()}`);
  },

  vaultBacklinkSearch: (q: string) =>
    request<BacklinkSearchResponse>(
      `/vault/backlinks/search?q=${encodeURIComponent(q)}`,
    ),

  vaultBacklinkReview: (path: string, aliases: string[] = []) =>
    request<NoteMentions>("/vault/backlinks/review", {
      method: "POST",
      body: JSON.stringify({ path, aliases }),
    }),

  vaultLinkMention: (body: {
    source_path: string;
    target_path: string;
    line: number;
    start: number;
    end: number;
    aliases?: string[];
  }) =>
    request<{ path: string; written: boolean; link: string }>(
      "/vault/backlinks/link",
      { method: "POST", body: JSON.stringify(body) },
    ),

  wikiBacklinkReview: (course?: string | null) =>
    request<Job>("/wiki/backlinks/review", {
      method: "POST",
      body: JSON.stringify({ course: course ?? null }),
    }),

  wikiBuild: (body: {
    course?: string | null;
    scope_path?: string | null;
    name?: string | null;
    force?: boolean;
  }) => request<Job>("/wiki/build", { method: "POST", body: JSON.stringify(body) }),

  wikiPages: (course?: string | null) =>
    request<WikiPagesResponse>(
      `/wiki/pages${course ? `?course=${encodeURIComponent(course)}` : ""}`,
    ),

  wikiGraph: (course?: string | null) =>
    request<WikiGraph>(
      `/wiki/graph${course ? `?course=${encodeURIComponent(course)}` : ""}`,
    ),

  vaultSearch: (q: string) =>
    request<{ results: { path: string; title: string }[] }>(
      `/vault/search?q=${encodeURIComponent(q)}`,
    ),

  vaultRename: (from_path: string, to_path: string) =>
    request<{ from: string; to: string; links_updated: number }>("/vault/rename", {
      method: "POST",
      body: JSON.stringify({ from_path, to_path }),
    }),

  vaultCopy: (from_path: string, to_path: string) =>
    request<{ from: string; to: string }>("/vault/copy", {
      method: "POST",
      body: JSON.stringify({ from_path, to_path }),
    }),

  vaultMove: (from_path: string, to_folder: string) =>
    request<{ from: string; to: string; type: "file" | "folder" }>("/vault/move", {
      method: "POST",
      body: JSON.stringify({ from_path, to_folder }),
    }),

  vaultImport: (source_paths: string[], target_folder: string) =>
    request<{
      count: number;
      imported: { source: string; path: string; type: "file" | "folder" }[];
    }>("/vault/import", {
      method: "POST",
      body: JSON.stringify({ source_paths, target_folder }),
    }),

  vaultMerge: (target_path: string, source_path: string, delete_source = false) =>
    request<{ target: string; source: string; deleted: unknown }>("/vault/merge", {
      method: "POST",
      body: JSON.stringify({ target_path, source_path, delete_source }),
    }),

  vaultSetProperty: (path: string, key: string, value: string) =>
    request<{ path: string; key: string; value: string }>("/vault/property", {
      method: "POST",
      body: JSON.stringify({ path, key, value }),
    }),

  vaultVersions: (path: string) =>
    request<{ path: string; versions: NoteVersion[] }>(
      `/vault/versions?path=${encodeURIComponent(path)}`,
    ),

  vaultRestoreVersion: (path: string, version_id: string) =>
    request<{ path: string; written: boolean }>("/vault/versions/restore", {
      method: "POST",
      body: JSON.stringify({ path, version_id }),
    }),

  vaultDelete: (path: string) =>
    request<{ deleted: string; backup: string }>("/vault/delete", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  vaultReveal: (path: string) =>
    request<{ revealed: string }>("/vault/reveal", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  vaultOpenExternal: (path: string) =>
    request<{ opened: string }>("/vault/open-external", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  vaultExportPdf: (path: string) =>
    request<{ pdf: string }>("/vault/export-pdf", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  transformationTemplates: () =>
    request<{ templates: TransformationTemplate[] }>("/transformations/templates"),

  runTransformation: (body: {
    template_id: number;
    target_kind: "document" | "vault_note" | "study_set";
    target_ref?: string | null;
    study_set_id?: number | null;
  }) =>
    request<{ run: Record<string, unknown>; job: Job }>("/transformations/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deepAsk: (body: {
    question: string;
    course?: string | null;
    scope_path?: string | null;
    study_set_id?: number | null;
    max_searches?: number;
  }) =>
    request<Job>("/ask/deep", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
