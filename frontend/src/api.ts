import type {
  AnalyzeReport,
  AppSettings,
  ChatResponse,
  ConceptProgress,
  CourseSummary,
  DailyPlan,
  DocumentRow,
  Health,
  LectureDocument,
  LecturePreview,
  LectureViewer,
  FormatPreview,
  NotePreview,
  NoteVersion,
  OrganizerMove,
  OrganizerPreview,
  PastPaperQuestion,
  QuizResult,
  SearchResponse,
  SubmitResult,
  TreeNode,
  VaultScope,
  VaultGraph,
  VaultNote,
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

export const api = {
  health: () => request<Health>("/health"),

  settings: () => request<AppSettings>("/settings"),

  saveSettings: (body: Omit<AppSettings, "vault_exists" | "lectures_root_exists">) =>
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
    week?: number | null;
    topic?: string | null;
    write?: boolean;
  }) =>
    request<NotePreview>("/notes/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generateQuiz: (body: {
    course?: string | null;
    scope_path?: string | null;
    scope_name?: string | null;
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

  vaultSearch: (q: string) =>
    request<{ results: { path: string; title: string }[] }>(
      `/vault/search?q=${encodeURIComponent(q)}`,
    ),

  vaultRename: (from_path: string, to_path: string) =>
    request<{ from: string; to: string }>("/vault/rename", {
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
};
