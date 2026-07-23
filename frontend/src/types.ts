export interface Citation {
  title: string;
  course: string | null;
  week: number | null;
  location: string | null;
  link: string;
  path: string;
  source_type: string | null;
  trust_level: number;
}

export interface SearchHit {
  chunk_id: number;
  document_id: number;
  heading: string | null;
  page_number: number | null;
  course: string | null;
  week: number | null;
  source_type: string | null;
  trust_level: number;
  title: string;
  path: string;
  score: number;
  retrieval: string;
  content?: string;
  citation: Citation;
}

export interface SearchResponse {
  query: string;
  used_vector: boolean;
  note: string | null;
  count: number;
  results: SearchHit[];
}

export interface ChatResponse {
  conversation_id: number;
  answer: string;
  citations: Citation[];
  sources: Array<Record<string, unknown> & { title: string; marker: string }>;
  warnings: string[];
  used_vector: boolean;
  model: string;
}

export interface NotePreview {
  title: string;
  target_path: string;
  content: string;
  sources: Array<Record<string, unknown> & { title: string; marker: string }>;
  warnings: string[];
  written: boolean;
  model: string;
}

export interface VoiceNoteStatus {
  enabled: boolean;
  model_path: string | null;
  model_exists: boolean;
  model_is_partial: boolean;
  whisper_cli_path: string;
  whisper_cli_available: boolean;
  ffmpeg_path: string;
  ffmpeg_available: boolean;
  language: string;
  max_upload_mb: number;
}

export interface VoiceNoteResult {
  transcript: string;
  markdown: string;
  title: string;
  model: string;
  whisper_model_path: string;
  written: boolean;
  target_path: string | null;
  audio_path: string | null;
}

export interface VoiceTranscriptionResult {
  transcript: string;
  whisper_model_path: string;
  audio_path: string | null;
}

export interface NoteTranslation {
  text: string;
  translation: string;
  source_language: "English";
  target_language: "Traditional Chinese";
  model: string;
}

export interface TranslatedNoteResult {
  source_path: string;
  path: string;
  title: string;
  blocks: number;
  written: boolean;
  status?: "running" | "succeeded" | "failed";
}

export interface CourseSummary {
  course: string;
  label: string;
  documents: number;
  chunks: number;
}

export interface VaultScope {
  id: string;
  name: string;
  kind: "course" | "folder" | "study_set";
  course: string | null;
  path: string;
  documents: number;
  study_set_id?: number;
}

export interface DocumentRow {
  id: number;
  title: string;
  week: number | null;
  document_type: string | null;
  source_type: string | null;
  trust_level: number;
  chunks: number;
  path: string;
}

export interface LectureDocument {
  id: number;
  title: string;
  path: string;
  relative_path: string;
  folder_course: string | null;
  course: string | null;
  week: number | null;
  source_type: string | null;
  chunks: number;
  extension: string;
}

export interface LecturePreview {
  id: number;
  title: string;
  path: string;
  course: string | null;
  week: number | null;
  extension: string;
  sections: { page: number | null; heading: string | null; content: string }[];
}

export interface LectureViewer {
  id: number;
  title: string;
  extension: string;
  pages: number;
}

export interface QuizQuestion {
  id: number;
  index: number;
  type: "mcq" | "short";
  question: string;
  options: string[] | null;
  difficulty: string;
  concept: string | null;
}

export interface QuizResult {
  quiz_id: number | null;
  course: string | null;
  week: number | null;
  topic: string | null;
  questions: QuizQuestion[];
  warnings: string[];
}

export interface GradedResult {
  question_id: number;
  concept: string | null;
  your_answer: string;
  correct_answer: string;
  outcome: "correct" | "partial" | "incorrect";
  score: number;
  explanation: string | null;
  feedback: string | null;
}

export interface SubmitResult {
  quiz_id: number;
  score: number;
  total: number;
  results: GradedResult[];
  progress: Record<string, { confidence: number; status: string; next_review: string | null }>;
}

export interface ConceptProgress {
  concept_id: number;
  name: string;
  course: string | null;
  confidence: number;
  status: string;
  correct: number;
  incorrect: number;
  partial: number;
  last_reviewed: string | null;
  next_review: string | null;
}

export interface PlanBlock {
  concept: string;
  concept_id: number;
  minutes: number;
  action: string;
  confidence: number;
  status: string;
  exam_frequency: number;
}

export interface DailyPlan {
  title: string;
  target_path: string;
  content: string;
  written: boolean;
  data: {
    course: string | null;
    date: string;
    available_minutes: number;
    exam_date: string | null;
    days_until_exam: number | null;
    blocks: PlanBlock[];
  };
}

export interface PastPaperQuestion {
  id: number;
  number: string | null;
  marks: number | null;
  concept: string | null;
  text: string;
}

export interface AnalyzeReport {
  course: string | null;
  documents: number;
  questions: number;
  concepts_updated: number;
  warnings: string[];
}

export interface TreeNode {
  name: string;
  path: string;
  type: "folder" | "file";
  children?: TreeNode[];
}

export interface NoteHeading {
  level: number;
  text: string;
  slug: string;
}

export interface VaultNote {
  path: string;
  name: string;
  content: string;
  frontmatter: Record<string, unknown>;
  headings: NoteHeading[];
  links: { name: string; path: string | null }[];
  backlinks: { path: string; title: string }[];
  editable: boolean;
}

export interface MentionSpan {
  line: number;
  start: number;
  end: number;
  snippet: string;
  hl_start: number;
  hl_end: number;
  reason?: string;
  confidence?: number;
}

export interface MentionGroup {
  path: string;
  title: string;
  mentions: MentionSpan[];
}

export interface NoteMentions {
  path: string;
  name: string;
  linked: MentionGroup[];
  unlinked: MentionGroup[];
  model?: string | null;
  reviewed?: number;
  candidates?: number;
  notice?: string | null;
}

export interface WikiBacklinkReviewTarget {
  path: string;
  title: string;
  aliases: string[];
  review: NoteMentions;
}

export interface WikiBacklinkReview {
  course: string | null;
  targets: WikiBacklinkReviewTarget[];
  pages_reviewed: number;
  suggestions: number;
  errors: { path: string; title: string; error: string }[];
}

export interface BacklinkSearchTarget {
  path: string;
  title: string;
  name: string;
  unlinked: MentionGroup[];
  count: number;
}

export interface BacklinkSearchResponse {
  query: string;
  targets: BacklinkSearchTarget[];
  count: number;
  mentions: number;
}

export interface GraphNode {
  id: string;
  title: string;
  folder: string;
  degree: number;
}

export interface VaultGraph {
  nodes: GraphNode[];
  edges: { source: string; target: string }[];
  stats: { notes: number; links: number };
}

export interface WikiPage {
  path: string;
  title: string;
  type: "map" | "concept" | "entity" | "source";
  sources: string[];
  summary: string;
  updated_at: string;
}

export interface WikiPagesResponse {
  course: string | null;
  pages: WikiPage[];
  has_purpose: boolean;
  index_path: string | null;
  log_path: string;
  purpose_path: string;
}

export interface WikiGraphNode {
  id: string;
  title: string;
  type: string;
  course: string | null;
  community: number;
  degree: number;
  flagged: boolean;
}

export interface WikiGraphEdge {
  source: string;
  target: string;
  weight: number;
  signals: { link: number; source: number; adamic: number; title: number; type: number };
}

export interface WikiGraph {
  nodes: WikiGraphNode[];
  edges: WikiGraphEdge[];
  communities: { id: number; size: number; cohesion: number; flagged: boolean }[];
  stats: { pages: number; edges: number; communities: number; cross_course_edges: number };
}

export interface OrganizerMove {
  from: string;
  to: string;
  reason: string;
}

export interface OrganizerPreview {
  summary: string;
  moves: OrganizerMove[];
  inventory_count: number;
  model: string;
}

export interface FormatPreview {
  path: string;
  before: string;
  after: string;
  changed: boolean;
  model: string;
}

export interface NoteVersion {
  id: string;
  timestamp: string;
  size: number;
  content: string;
}

export interface Health {
  status: string;
  version: string;
  vault_root: string;
  vault_exists: boolean;
  output_root: string;
  default_provider: string;
  external_sources: number;
}

export interface StudySetItem {
  id?: number;
  kind: "document" | "vault_note" | "generated_note";
  ref: string | number;
  mode: "full" | "snippets" | "exclude";
}

export interface StudySet {
  id: number;
  name: string;
  course: string | null;
  scope_path: string | null;
  items: StudySetItem[];
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: number;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress_current: number;
  progress_total: number;
  message: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface TransformationTemplate {
  id: number;
  name: string;
  description: string;
  prompt: string;
  apply_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskModelOverride {
  provider: ChatProvider | null;
  model: string | null;
  base_url: string | null;
}

export type ChatProvider = "lmstudio" | "openai" | "anthropic" | "echo";

export type TaskModelName =
  | "chat"
  | "deep_ask"
  | "transformations"
  | "quiz_marking"
  | "translation"
  | "voice_notes"
  | "wiki";

export interface AppSettings {
  vault_root: string;
  vault_exists: boolean;
  lectures_root: string | null;
  lectures_root_exists: boolean | null;
  default_provider: ChatProvider;
  llm_base_url: string;
  llm_model: string;
  openai_base_url: string;
  openai_model: string;
  anthropic_model: string;
  openai_key_set: boolean;
  anthropic_key_set: boolean;
  embedding_provider: "lmstudio" | "hash";
  embedding_base_url: string | null;
  embedding_model: string;
  task_models: Record<TaskModelName, TaskModelOverride>;
  chunk_tokens: number;
  chunk_overlap_tokens: number;
  min_chunk_tokens: number;
  temperature: number;
  require_citations: boolean;
}

/** The editable subset sent to PUT /settings (status fields are server-derived). */
export interface SettingsPayload {
  vault_root: string;
  lectures_root: string | null;
  default_provider: ChatProvider;
  llm_base_url: string;
  llm_model: string;
  openai_base_url: string;
  openai_model: string;
  anthropic_model: string;
  api_key?: string | null;
  embedding_provider: "lmstudio" | "hash";
  embedding_base_url: string | null;
  embedding_model: string;
  task_models: AppSettings["task_models"];
  chunk_tokens: number;
  chunk_overlap_tokens: number;
  min_chunk_tokens: number;
  temperature: number;
  require_citations: boolean;
}
