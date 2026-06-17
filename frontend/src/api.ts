import type {
  ChatResponse,
  CourseSummary,
  DocumentRow,
  Health,
  NotePreview,
  SearchResponse,
} from "./types";

// Calls go through the Vite proxy (/api -> backend). Override with VITE_API_BASE.
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
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
};
