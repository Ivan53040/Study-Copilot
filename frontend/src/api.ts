import type {
  AnalyzeReport,
  ChatResponse,
  ConceptProgress,
  CourseSummary,
  DailyPlan,
  DocumentRow,
  Health,
  NotePreview,
  PastPaperQuestion,
  QuizResult,
  SearchResponse,
  SubmitResult,
  TreeNode,
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

  courses: () => request<{ courses: CourseSummary[] }>("/courses"),

  documents: (course: string) =>
    request<{ course: string; count: number; documents: DocumentRow[] }>(
      `/courses/${encodeURIComponent(course)}/documents`,
    ),

  search: (body: {
    query: string;
    course?: string | null;
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
    conversation_id?: number | null;
  }) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generateNote: (body: {
    course?: string | null;
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
    week?: number | null;
    topic?: string | null;
    num_questions?: number;
  }) =>
    request<QuizResult>("/exams/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  vaultTree: () => request<TreeNode>("/vault/tree"),

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

  vaultGraph: () => request<VaultGraph>("/vault/graph"),

  vaultSearch: (q: string) =>
    request<{ results: { path: string; title: string }[] }>(
      `/vault/search?q=${encodeURIComponent(q)}`,
    ),
};
