import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";
import { api } from "../api";
import { ModelMenu, effectiveChoice, useModelChoice, useModelOptions } from "../models";
import type {
  ChatRequestBody,
  ChatSource,
  ChatStreamEvent,
  Citation,
  DocumentRow,
  StudySetItem,
  VaultScope,
} from "../types";
import { BrandMark, Icon } from "../icons";
import { SourcePageViewer, TRUST_LABEL, hasPageImage, useDismiss } from "../components";
import { rankScopes, scopeKindLabel, useScopes } from "../CoursePicker";

type ContextMode = "retrieval" | "manual" | "hybrid";

export interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Saved message id (edit / regenerate replace from the question's id). */
  messageId?: number | null;
  citations?: Citation[];
  sources?: ChatSource[];
  warnings?: string[];
  failed?: boolean;
  question?: string;
  /** Streaming state of an answer being written. */
  streaming?: boolean;
  phase?: "search" | "read" | "think" | "write";
  thinking?: string;
  thinkStartedAt?: number;
  thinkMs?: number;
  stopped?: boolean;
  /** The note a question was asked about (note-scoped chat). */
  notePath?: string | null;
}

export interface QuizFromAnswer {
  question: string;
  course: string | null;
  documentIds: number[];
  notePath?: string | null;
}

export interface ActiveNote {
  path: string;
  title: string;
}

export interface ChatPageProps {
  /** Load this saved conversation on mount (null = a new chat). */
  conversationId?: number | null;
  /** Side-panel variant used next to notes and other tools. */
  compact?: boolean;
  userName?: string;
  vaultRoot?: string | null;
  onConversationCreated?: (id: number) => void;
  onActivity?: () => void;
  onOpenNote?: (path: string) => void;
  onNavigate?: (tab: string) => void;
  /** The note open next to this chat; questions default to it. */
  activeNote?: ActiveNote | null;
  /** "Quiz me on this" from an answer. */
  onQuiz?: (request: QuizFromAnswer) => void;
  /** Text to put in the composer when the chat opens. */
  initialInput?: string;
  /** Show the upcoming-deadline / reviews-due nudge on the home screen. */
  showToday?: boolean;
}

const MODE_COPY: Record<ContextMode, { label: string; hint: string }> = {
  retrieval: { label: "Auto", hint: "Search your notes for the most relevant passages." },
  manual: { label: "Selected", hint: "Answer only from the sources you tick below." },
  hybrid: { label: "Both", hint: "Your ticked sources, plus the best search results." },
};

const SUGGESTIONS: { icon: string; label: string; prompt?: string; tab?: string }[] = [
  { icon: "lightbulb", label: "Explain a concept", prompt: "Explain the difference between " },
  { icon: "graduation-cap", label: "Quiz me", tab: "quiz" },
  { icon: "pencil", label: "Revision note", tab: "generate" },
  { icon: "calendar", label: "Plan my day", tab: "plan" },
];

let turnSeq = 0;
const nextId = () => `t${++turnSeq}`;

function greeting(name: string) {
  const hour = new Date().getHours();
  const who = name.trim() ? `, ${name.trim()}` : "";
  if (hour < 5) return `Still studying${who}?`;
  if (hour < 12) return `Good morning${who}`;
  if (hour < 18) return `Good afternoon${who}`;
  return `Good evening${who}`;
}

export function toVaultRelative(path: string, vaultRoot?: string | null): string | null {
  if (!vaultRoot) return null;
  const norm = (value: string) => value.replace(/\\/g, "/").replace(/\/+$/, "");
  const root = norm(vaultRoot);
  const full = norm(path);
  if (full.toLowerCase().startsWith(root.toLowerCase() + "/")) return full.slice(root.length + 1);
  return null;
}

function stripMarkers(text: string) {
  return text.replace(/\s?\[S\d+\]/g, "");
}

const STOPPED_NOTE = "Stopped before the answer was finished.";

/** Close a half-written `**bold**` or `code` span so partial text renders cleanly. */
function closeOpenMarkdown(text: string) {
  let out = text;
  const fences = (out.match(/```/g) ?? []).length;
  if (fences % 2) return `${out}\n\`\`\``;
  const inline = out.replace(/```[\s\S]*?```/g, "");
  if (((inline.match(/`/g) ?? []).length) % 2) out += "`";
  if (((inline.replace(/`[^`]*`/g, "").match(/\*\*/g) ?? []).length) % 2) out = out.replace(/\s+$/, "") + "**";
  return out;
}

function noteTitle(path: string) {
  return (path.split("/").pop() ?? path).replace(/\.md$/i, "");
}

/* ------------------------------------------------------------------------ */
/* Composer                                                                  */
/* ------------------------------------------------------------------------ */

function ScopeMenu({
  scope,
  scopes,
  onChange,
  compact,
  dropDown,
}: {
  scope: VaultScope | null;
  scopes: VaultScope[];
  onChange: (scope: VaultScope | null) => void;
  compact?: boolean;
  dropDown?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrap = useRef<HTMLDivElement>(null);
  useDismiss(open, () => setOpen(false), [wrap]);
  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();
    // The fuzzy ranker only scores Latin letters and digits; for other scripts
    // (e.g. Chinese course names) fall back to a plain substring filter.
    const pool = q && /[^\x00-\x7f]/.test(q)
      ? scopes.filter((item) => item.name.toLowerCase().includes(q))
      : scopes;
    return rankScopes(pool, query).slice(0, 60);
  }, [scopes, query]);

  const choose = (value: VaultScope | null) => {
    onChange(value);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="menu-wrap" ref={wrap}>
      <button
        type="button"
        className={`tool-btn${scope ? " on" : ""}`}
        title={scope ? `Answering from ${scope.name}` : "Answering from all notes"}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name={scope?.kind === "study_set" ? "layers" : "book-open"} size={15} />
        <span className="scope-name">{scope?.name ?? (compact ? "All notes" : "All notes")}</span>
        <Icon name="chevron-down" size={13} />
      </button>
      {open && (
        <div className={`popover composer-pop${dropDown ? "" : ""}`} role="dialog">
          <input
            className="popover-search"
            autoFocus
            value={query}
            placeholder="Search courses, folders and study sets…"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing || event.keyCode === 229) return;
              if (event.key === "Enter" && ranked[0]) choose(ranked[0]);
            }}
          />
          <div className="popover-scroll">
            {!query && (
              <button type="button" className="popover-item" onClick={() => choose(null)}>
                <Icon name="library" size={15} />
                <span className="grow">All notes</span>
                {!scope && <Icon name="check" size={15} />}
              </button>
            )}
            {ranked.map((item) => (
              <button
                type="button"
                key={item.id}
                className="popover-item"
                onClick={() => choose(item)}
              >
                <Icon name={item.kind === "study_set" ? "layers" : item.kind === "course" ? "book-open" : "folder"} size={15} />
                <span className="grow">
                  {item.name}
                  <br />
                  <small>{scopeKindLabel(item)} · {item.documents} docs</small>
                </span>
                {scope?.id === item.id && <Icon name="check" size={15} />}
              </button>
            ))}
            {!ranked.length && <div className="popover-empty">No matching course or folder.</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function SourcesMenu({
  scope,
  mode,
  onMode,
  docs,
  items,
  onToggle,
  onDocMode,
}: {
  scope: VaultScope | null;
  mode: ContextMode;
  onMode: (mode: ContextMode) => void;
  docs: DocumentRow[];
  items: StudySetItem[];
  onToggle: (doc: DocumentRow, on: boolean) => void;
  onDocMode: (doc: DocumentRow, mode: StudySetItem["mode"]) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useDismiss(open, () => setOpen(false), [wrap]);
  const selected = items.filter((item) => item.mode !== "exclude").length;
  const approxTokens = useMemo(() => {
    const ids = new Set(
      items.filter((item) => item.kind === "document" && item.mode !== "exclude").map((item) => Number(item.ref)),
    );
    return docs.filter((doc) => ids.has(doc.id)).reduce((total, doc) => total + doc.chunks * 220, 0);
  }, [items, docs]);

  return (
    <div className="menu-wrap" ref={wrap}>
      <button
        type="button"
        className={`tool-btn icon-only${selected || mode !== "retrieval" ? " on" : ""}`}
        title="Choose sources"
        aria-label="Choose sources"
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="plus" size={16} />
        {selected > 0 && <span className="tool-count">{selected}</span>}
      </button>
      {open && (
        <div className="popover composer-pop" role="dialog">
          <div className="ctx-mode">
            <div className="segmented" role="radiogroup" aria-label="Answer from">
              {(Object.keys(MODE_COPY) as ContextMode[]).map((key) => (
                <button
                  type="button"
                  key={key}
                  role="radio"
                  aria-checked={mode === key}
                  className={mode === key ? "on" : ""}
                  onClick={() => onMode(key)}
                >
                  {MODE_COPY[key].label}
                </button>
              ))}
            </div>
            <p>{MODE_COPY[mode].hint}</p>
          </div>
          {scope?.kind === "study_set" ? (
            <div className="popover-empty">This study set supplies its own saved sources.</div>
          ) : !scope ? (
            <div className="popover-empty">Pick a course or folder first to tick specific sources.</div>
          ) : docs.length ? (
            <>
              <div className="popover-label">
                {scope.name} · {selected} selected
                {approxTokens ? ` · ~${approxTokens.toLocaleString()} tokens` : ""}
              </div>
              <div className="popover-scroll">
                {docs.map((doc) => {
                  const item = items.find(
                    (candidate) => candidate.kind === "document" && Number(candidate.ref) === doc.id,
                  );
                  return (
                    <label className="ctx-doc" key={doc.id}>
                      <input
                        type="checkbox"
                        checked={Boolean(item)}
                        onChange={(event) => onToggle(doc, event.target.checked)}
                      />
                      <span title={doc.title}>{doc.title}</span>
                      <select
                        value={item?.mode ?? "snippets"}
                        disabled={!item}
                        onChange={(event) => onDocMode(doc, event.target.value as StudySetItem["mode"])}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <option value="snippets">Snippets</option>
                        <option value="full">Full</option>
                      </select>
                    </label>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="popover-empty">No indexed documents in this scope yet.</div>
          )}
        </div>
      )}
    </div>
  );
}

function Composer({
  value,
  onChange,
  onSend,
  busy,
  placeholder,
  autoFocus,
  textareaRef,
  tools,
  model,
  onStop,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  placeholder: string;
  autoFocus?: boolean;
  textareaRef: RefObject<HTMLTextAreaElement>;
  tools: ReactNode;
  /** The model menu, next to the send button. */
  model?: ReactNode;
  /** While an answer streams, the send button becomes Stop. */
  onStop?: () => void;
}) {
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [value, textareaRef]);

  const canSend = value.trim().length > 0 && !busy;
  return (
    <div
      className="composer"
      onMouseDown={(event) => {
        const target = event.target as HTMLElement;
        if (!target.closest("textarea, button, input, select, label, .popover")) {
          event.preventDefault();
          textareaRef.current?.focus();
        }
      }}
    >
      <textarea
        ref={textareaRef}
        value={value}
        rows={1}
        autoFocus={autoFocus}
        placeholder={placeholder}
        aria-label="Message"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          // Let IME composition (e.g. Zhuyin / Pinyin) finish before Enter sends.
          if (event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (canSend) onSend();
          }
        }}
      />
      <div className="composer-row">
        {tools}
        <div className="grow" />
        {model}
        {busy && onStop ? (
          <button
            type="button"
            className="send-btn stop-btn"
            aria-label="Stop answering"
            title="Stop"
            onClick={onStop}
          >
            <Icon name="stop" size={14} />
          </button>
        ) : (
          <button
            type="button"
            className="send-btn"
            aria-label="Send message"
            title="Send (Enter)"
            disabled={!canSend}
            onClick={onSend}
          >
            <Icon name="arrow-up" size={17} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Assistant answer                                                          */
/* ------------------------------------------------------------------------ */

type SourceRef = {
  num: string;
  title: string;
  meta: string;
  trust: number;
  path: string;
  documentId?: number | null;
  page?: number | null;
};

function sourceRefs(turn: Turn): SourceRef[] {
  const markers: string[] = [];
  for (const match of turn.content.matchAll(/\[S(\d+)\]/g)) {
    if (!markers.includes(match[1])) markers.push(match[1]);
  }
  const bySid = new Map((turn.sources ?? []).map((source) => [source.marker, source]));
  const modelDown = turn.warnings?.some((warning) => warning.startsWith("Chat model unavailable"));
  if (bySid.size && !markers.length && modelDown) {
    // The model was unreachable: list what retrieval found so the answer's
    // "relevant sources below" is true.
    markers.push(...(turn.sources ?? []).map((source) => source.marker.slice(1)));
  }
  if (bySid.size) {
    return markers
      .map((num) => bySid.get(`S${num}`))
      .filter((source): source is ChatSource => Boolean(source))
      .map((source) => ({
        num: source.marker.slice(1),
        title: source.title,
        meta: [
          source.heading && source.heading !== source.title ? source.heading : null,
          source.page_number != null ? `p. ${source.page_number}` : null,
          source.course,
          source.week != null ? `Week ${source.week}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        trust: source.trust_level,
        path: source.path,
        documentId: source.document_id,
        page: source.page_number,
      }));
  }
  return (turn.citations ?? []).map((cite, index) => ({
    num: String(index + 1),
    title: cite.title,
    meta: [
      cite.location?.replace(/^Section:\s*/, ""),
      cite.course,
      cite.week != null ? `Week ${cite.week}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
    trust: cite.trust_level,
    path: cite.path,
    documentId: cite.document_id,
    page: cite.page_number,
  }));
}

function useTicker(active: boolean, ms = 1000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), ms);
    return () => window.clearInterval(timer);
  }, [active, ms]);
}

function seconds(ms: number) {
  const value = Math.max(1, Math.round(ms / 1000));
  return `${value} second${value === 1 ? "" : "s"}`;
}

/** Live "Thinking…" line for reasoning models; expands to show the reasoning. */
function ThinkingDisclosure({ turn }: { turn: Turn }) {
  const [open, setOpen] = useState(false);
  const live = Boolean(turn.streaming && turn.phase === "think");
  useTicker(live);
  if (!turn.thinking) return null;
  const elapsed = turn.thinkMs ?? (turn.thinkStartedAt ? Date.now() - turn.thinkStartedAt : 0);
  return (
    <div className={`think-block${open ? " open" : ""}`}>
      <button type="button" className="think-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {live ? (
          <span className="thinking-text">Thinking… {elapsed >= 1000 ? seconds(elapsed) : ""}</span>
        ) : (
          <span>Thought for {seconds(elapsed)}</span>
        )}
        <Icon name="chevron-down" size={13} />
      </button>
      {open && <div className="think-body">{turn.thinking}</div>}
    </div>
  );
}

function PhaseLine({ turn }: { turn: Turn }) {
  const count = turn.sources?.length ?? 0;
  const label =
    turn.phase === "search"
      ? turn.notePath
        ? `Reading ${noteTitle(turn.notePath)}…`
        : "Searching your notes…"
      : turn.phase === "read"
        ? count
          ? `Reading ${count} ${count === 1 ? "source" : "sources"}…`
          : "Writing an answer…"
        : null;
  if (!label) return null;
  return (
    <div className="thinking" aria-live="polite">
      <BrandMark size={20} />
      <span className="thinking-text">{label}</span>
    </div>
  );
}

function AssistantTurn({
  turn,
  isLast,
  vaultRoot,
  onOpenNote,
  onRetry,
  onRegenerate,
  onQuiz,
  busy = false,
}: {
  turn: Turn;
  isLast: boolean;
  vaultRoot?: string | null;
  onOpenNote?: (path: string) => void;
  onRetry: (turn: Turn) => void;
  onRegenerate?: () => void;
  onQuiz?: () => void;
  busy?: boolean;
}) {
  const [hot, setHot] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [viewer, setViewer] = useState<SourceRef | null>(null);
  const refs = useMemo(() => sourceRefs(turn), [turn]);
  const byNum = useMemo(() => new Map(refs.map((ref) => [ref.num, ref])), [refs]);

  const openSource = useCallback(
    (ref: SourceRef) => {
      if (hasPageImage(ref.path, ref.documentId, ref.page)) {
        setViewer(ref);
        return;
      }
      const rel = toVaultRelative(ref.path, vaultRoot);
      if (rel && onOpenNote) onOpenNote(rel);
    },
    [vaultRoot, onOpenNote],
  );

  const components = useMemo<Components>(
    () => ({
      ...mdComponents,
      sup({ node, children, ...props }: any) {
        const sid = props["data-cite"] as string | undefined;
        if (!sid) return <sup {...props}>{children}</sup>;
        const num = sid.slice(1);
        const ref = byNum.get(num);
        return (
          <button
            type="button"
            className={`cite-chip${ref ? "" : " invalid"}${hot === num ? " hot" : ""}`}
            title={ref ? `${ref.title}${ref.meta ? ` — ${ref.meta}` : ""}` : "This source was not provided to the model"}
            onMouseEnter={() => setHot(num)}
            onMouseLeave={() => setHot(null)}
            onClick={() => ref && openSource(ref)}
          >
            {num}
          </button>
        );
      },
    }),
    [byNum, hot, openSource],
  );

  if (turn.failed) {
    return (
      <div className={`turn turn-assistant${isLast ? " last" : ""}`}>
        <div className="turn-warning turn-error">
          <Icon name="alert-triangle" size={15} />
          <span>{turn.content}</span>
          {turn.question && (
            <button type="button" className="ghost small" disabled={busy} onClick={() => onRetry(turn)}>
              <Icon name="rotate-ccw" size={13} /> Try again
            </button>
          )}
        </div>
      </div>
    );
  }

  const streaming = Boolean(turn.streaming);
  const partial = streaming || Boolean(turn.warnings?.includes(STOPPED_NOTE));
  // While streaming, hide a half-written citation marker such as "[S".
  const visible = streaming ? turn.content.replace(/\s?\[(S\d*)?$/, "") : turn.content;
  const markdown = (partial ? closeOpenMarkdown(visible) : visible).replace(
    /\[S(\d+)\]/g,
    '<sup data-cite="S$1">$1</sup>',
  );
  const showActions = !streaming && turn.content.trim().length > 0;
  return (
    <div className={`turn turn-assistant${isLast ? " last" : ""}${streaming ? " streaming" : ""}`}>
      <ThinkingDisclosure turn={turn} />
      {streaming && !visible && <PhaseLine turn={turn} />}
      {visible && (
        <div className="md">
          <ReactMarkdown remarkPlugins={mdRemarkPlugins} rehypePlugins={mdRehypePlugins} components={components}>
            {markdown}
          </ReactMarkdown>
        </div>
      )}
      {refs.length > 0 && (
        <div className="turn-sources" aria-label="Sources">
          {refs.map((ref) => (
            <button
              type="button"
              key={ref.num}
              className={`source-card${hot === ref.num ? " hot" : ""}`}
              title={`${ref.title}${ref.meta ? ` — ${ref.meta}` : ""} · ${TRUST_LABEL[ref.trust] ?? ""}`}
              onMouseEnter={() => setHot(ref.num)}
              onMouseLeave={() => setHot(null)}
              onClick={() => openSource(ref)}
            >
              <span className="source-num">{ref.num}</span>
              <span className="source-title">{ref.title}</span>
              {ref.meta && <span className="source-meta">{ref.meta}</span>}
              <span className={`trust-dot t${ref.trust}`} aria-label={TRUST_LABEL[ref.trust]} />
            </button>
          ))}
        </div>
      )}
      {!streaming &&
        turn.warnings?.map((warning, index) => (
          <div className={`turn-warning${warning === STOPPED_NOTE ? " quiet" : ""}`} key={index}>
            <Icon name={warning === STOPPED_NOTE ? "stop" : "alert-triangle"} size={14} />
            <span>{warning}</span>
          </div>
        ))}
      {showActions && (
        <div className="turn-actions">
          <button
            type="button"
            className="icon-btn"
            title={copied ? "Copied" : "Copy answer"}
            aria-label="Copy answer"
            onClick={() => {
              navigator.clipboard?.writeText(stripMarkers(turn.content)).then(() => {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1500);
              }).catch(() => {});
            }}
          >
            <Icon name={copied ? "check" : "copy"} size={15} />
          </button>
          {onRegenerate && (
            <button
              type="button"
              className="icon-btn"
              title="Regenerate answer"
              aria-label="Regenerate answer"
              disabled={busy}
              onClick={onRegenerate}
            >
              <Icon name="rotate-ccw" size={15} />
            </button>
          )}
          {onQuiz && refs.length > 0 && (
            <button
              type="button"
              className="ghost small quiz-btn"
              title="Make a short quiz from this answer's sources"
              onClick={onQuiz}
            >
              <Icon name="graduation-cap" size={14} /> Quiz me on this
            </button>
          )}
          {refs.length > 0 && (
            <span className="turn-meta">
              {refs.length} {refs.length === 1 ? "source" : "sources"}
            </span>
          )}
        </div>
      )}
      {viewer && viewer.documentId != null && viewer.page != null && (
        <SourcePageViewer
          documentId={viewer.documentId}
          page={viewer.page}
          title={viewer.title}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  );
}

function UserTurn({
  turn,
  canEdit,
  onEdit,
}: {
  turn: Turn;
  canEdit: boolean;
  onEdit: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(turn.content);
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [draft, editing]);

  if (editing) {
    const submit = () => {
      const text = draft.trim();
      if (!text) return;
      setEditing(false);
      onEdit(text);
    };
    return (
      <div className="turn turn-user-edit">
        <textarea
          ref={ref}
          value={draft}
          autoFocus
          aria-label="Edit your message"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.keyCode === 229) return;
            if (event.key === "Escape") setEditing(false);
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="edit-row">
          <span className="edit-note">Sending replaces the replies after this message.</span>
          <button type="button" className="ghost small" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button type="button" className="primary small" disabled={!draft.trim()} onClick={submit}>
            Send
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="turn turn-user-wrap">
      {turn.notePath && (
        <div className="turn-note-chip" title={turn.notePath}>
          <Icon name="file-text" size={12} /> {noteTitle(turn.notePath)}
        </div>
      )}
      <div className="turn-user">{turn.content}</div>
      {canEdit && (
        <div className="user-actions">
          <button
            type="button"
            className="icon-btn"
            title="Edit message"
            aria-label="Edit message"
            onClick={() => {
              setDraft(turn.content);
              setEditing(true);
            }}
          >
            <Icon name="pencil" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

function NoteScopeChip({
  note,
  on,
  onToggle,
}: {
  note: ActiveNote;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={`tool-btn note-chip${on ? " on" : ""}`}
      aria-pressed={on}
      title={
        on
          ? `Answering from “${note.title}” and the notes it links to. Click to search all notes instead.`
          : `Click to answer from “${note.title}” and its linked notes`
      }
      onClick={onToggle}
    >
      <Icon name="file-text" size={14} />
      <span className="scope-name">{on ? note.title : "This note"}</span>
    </button>
  );
}

/** One line on the home screen: the next deadline and reviews due (links to Today). */
function TodayNudge({ onOpen }: { onOpen: () => void }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .today()
      .then((today) => {
        if (!alive) return;
        const bits: string[] = [];
        const next = today.deadlines[0];
        if (next && next.days_until <= 30) {
          const when =
            next.days_until <= 0 ? "today" : next.days_until === 1 ? "tomorrow" : `in ${next.days_until} days`;
          bits.push(`${next.title} ${when}`);
        }
        if (today.due_count) {
          bits.push(`${today.due_count} ${today.due_count === 1 ? "topic" : "topics"} to review`);
        }
        setText(bits.length ? bits.join(" · ") : null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  if (!text) return null;
  return (
    <button type="button" className="today-nudge" onClick={onOpen}>
      <Icon name="sun" size={14} />
      {text}
      <Icon name="chevron-right" size={13} />
    </button>
  );
}

/* ------------------------------------------------------------------------ */
/* Page                                                                      */
/* ------------------------------------------------------------------------ */

type Pending = { content: string; thinking: string };

export function ChatPage({
  conversationId = null,
  compact = false,
  userName = "",
  vaultRoot,
  onConversationCreated,
  onActivity,
  onOpenNote,
  onNavigate,
  activeNote = null,
  onQuiz,
  initialInput = "",
  showToday = false,
}: ChatPageProps) {
  const modelChoice = useModelChoice();
  const { options: modelList } = useModelOptions();
  const modelMenu = <ModelMenu onSetup={onNavigate ? () => onNavigate("settings") : undefined} />;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState(initialInput);
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [contextMode, setContextMode] = useState<ContextMode>("retrieval");
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [contextItems, setContextItems] = useState<StudySetItem[]>([]);
  const [convCourse, setConvCourse] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(Boolean(conversationId));
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [noteScopeOn, setNoteScopeOn] = useState(true);
  const scopes = useScopes();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const convIdRef = useRef<number | null>(conversationId);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const noteScope = activeNote && noteScopeOn ? activeNote : null;

  // A chat opened with a prepared question ("Ask" on Today): caret at the end.
  useEffect(() => {
    if (!initialInput) return;
    const el = textareaRef.current;
    el?.focus();
    el?.setSelectionRange(el.value.length, el.value.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load a saved conversation once, on mount. (The parent remounts this page via
  // `key` to switch conversations, so a newly created id must not reload it.)
  const initialConversationId = useRef(conversationId).current;
  useEffect(() => {
    if (!initialConversationId) return;
    let alive = true;
    setLoadingHistory(true);
    api
      .conversation(initialConversationId)
      .then((detail) => {
        if (!alive) return;
        setConvCourse(detail.course);
        setTurns(
          detail.messages.map((message) => ({
            id: nextId(),
            role: message.role,
            content: message.content,
            messageId: message.id ?? null,
            citations: message.extra?.citations,
            sources: message.extra?.sources,
            warnings: message.extra?.warnings,
          })),
        );
      })
      .catch((e) => alive && setHistoryError((e as Error).message))
      .finally(() => alive && setLoadingHistory(false));
    return () => {
      alive = false;
    };
  }, [initialConversationId]);

  // Restore the course scope a saved conversation was asked in (once, when the
  // scope list arrives) so choosing "All notes" afterwards sticks.
  const scopeRestored = useRef(false);
  useEffect(() => {
    if (scopeRestored.current || !convCourse || !scopes.length) return;
    scopeRestored.current = true;
    const match = scopes.find((item) => item.kind === "course" && item.course === convCourse);
    if (match) setScope((current) => current ?? match);
  }, [convCourse, scopes]);

  useEffect(() => {
    setDocs([]);
    setContextItems([]);
    if (!scope || scope.kind === "study_set") return;
    api
      .scopeDocuments(scope.path)
      .then((result) => setDocs(result.documents))
      .catch(() => {});
  }, [scope]);

  // Follow the answer as it streams, unless the reader scrolled up to read.
  useEffect(() => {
    const el = threadRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [turns, loadingHistory]);

  const onThreadScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const setDocumentContext = (doc: DocumentRow, mode: StudySetItem["mode"]) => {
    setContextItems((current) => {
      const rest = current.filter(
        (item) => !(item.kind === "document" && Number(item.ref) === doc.id),
      );
      if (mode === "exclude") return rest;
      return [...rest, { kind: "document", ref: doc.id, mode }];
    });
  };

  const patchTurn = useCallback((id: string, patch: (turn: Turn) => Partial<Turn>) => {
    setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, ...patch(turn) } : turn)));
  }, []);

  /**
   * Ask `message`. With `replace`, the saved question `replace.messageId` (at
   * `replace.index` in the thread) and everything after it are replaced — used
   * by edit, regenerate and retry.
   */
  const ask = async (message: string, replace?: { index: number; messageId: number | null }) => {
    if (!message || loading) return;
    const contextModeForSend: ContextMode =
      contextMode === "retrieval" || contextItems.length > 0 ? contextMode : "retrieval";
    const userId = nextId();
    const answerId = nextId();
    const notePath = noteScope?.path ?? null;
    // The thread as it was, to put back if this is stopped before it starts.
    const before: { turns: Turn[] | null } = { turns: null };
    setTurns((current) => {
      before.turns = current;
      return [
        ...(replace ? current.slice(0, replace.index) : current),
        { id: userId, role: "user", content: message, notePath },
        { id: answerId, role: "assistant", content: "", streaming: true, phase: "search", notePath },
      ];
    });
    stickToBottom.current = true;
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;
    const askedAt = Date.now();
    let started = false;
    const pending: Pending = { content: "", thinking: "" };
    let flushTimer: number | null = null;
    const flush = () => {
      flushTimer = null;
      if (!pending.content && !pending.thinking) return;
      const add = { ...pending };
      pending.content = "";
      pending.thinking = "";
      patchTurn(answerId, (turn) => {
        const next: Partial<Turn> = {};
        if (add.thinking) {
          next.thinking = (turn.thinking ?? "") + add.thinking;
          next.thinkStartedAt = turn.thinkStartedAt ?? Date.now();
          if (!turn.content) next.phase = "think";
        }
        if (add.content) {
          next.content = turn.content + add.content;
          next.phase = "write";
          if (turn.thinkStartedAt && turn.thinkMs == null) next.thinkMs = Date.now() - turn.thinkStartedAt;
        }
        return next;
      });
    };
    const schedule = () => {
      if (flushTimer == null) flushTimer = window.setTimeout(flush, 50);
    };

    const body: ChatRequestBody = notePath
      ? { message, note_path: notePath, conversation_id: convIdRef.current }
      : {
          message,
          course: scope?.course ?? null,
          scope_path: scope?.kind === "study_set" ? null : scope?.path ?? null,
          study_set_id: scope?.study_set_id ?? null,
          context_mode: contextModeForSend,
          context_items: contextItems,
          conversation_id: convIdRef.current,
        };
    if (replace?.messageId != null) body.replace_from_id = replace.messageId;
    const chosenModel = effectiveChoice(modelList, modelChoice);
    if (chosenModel) {
      body.provider = chosenModel.provider;
      body.model = chosenModel.model;
    }

    const onEvent = (event: ChatStreamEvent) => {
      if (event.type === "start") {
        started = true;
        patchTurn(userId, () => ({ messageId: event.user_message_id }));
        patchTurn(answerId, () => ({ sources: event.sources, phase: "read" }));
        if (event.conversation_id !== convIdRef.current) {
          convIdRef.current = event.conversation_id;
          // A late reply from a chat the user has already left must not
          // re-select it in the header / sidebar.
          if (mounted.current) onConversationCreated?.(event.conversation_id);
          onActivity?.();
        }
      } else if (event.type === "thinking") {
        pending.thinking += event.text;
        schedule();
      } else if (event.type === "delta") {
        pending.content += event.text;
        schedule();
      } else if (event.type === "rethink") {
        // The model's reasoning began in its prompt: what looked like the
        // answer so far was thinking.
        if (flushTimer != null) window.clearTimeout(flushTimer);
        flush();
        patchTurn(answerId, (turn) => ({
          thinking: (turn.thinking ?? "") + turn.content,
          thinkStartedAt: turn.thinkStartedAt ?? askedAt,
          thinkMs: undefined,
          content: "",
          phase: "think",
        }));
      } else if (event.type === "done") {
        if (flushTimer != null) window.clearTimeout(flushTimer);
        flush();
        patchTurn(answerId, (turn) => ({
          content: event.answer,
          messageId: event.message_id ?? null,
          citations: event.citations,
          sources: event.sources,
          warnings: event.warnings,
          streaming: false,
          phase: undefined,
          thinkMs:
            turn.thinkMs ?? (turn.thinkStartedAt ? Date.now() - turn.thinkStartedAt : undefined),
        }));
        if (event.user_message_id) patchTurn(userId, () => ({ messageId: event.user_message_id }));
      }
    };

    try {
      await api.chatStream(body, { signal: controller.signal, onEvent });
    } catch (e) {
      if (flushTimer != null) window.clearTimeout(flushTimer);
      flush();
      if (controller.signal.aborted && !started) {
        // Stopped before the answer started: the backend undoes the question
        // (an edit or regenerate gets back what it replaced), so the thread
        // goes back to how it was and a new or edited question to the box.
        const previous = before.turns;
        const regenerated =
          replace != null && previous?.[replace.index]?.content === message;
        setTurns((current) =>
          previous ?? current.filter((turn) => turn.id !== userId && turn.id !== answerId),
        );
        if (!regenerated) setInput((current) => (current.trim() ? current : message));
      } else if (controller.signal.aborted) {
        // Stopped: keep what was written (the backend saved it too).
        patchTurn(answerId, (turn) => ({
          streaming: false,
          phase: undefined,
          stopped: true,
          warnings: [STOPPED_NOTE],
          thinkMs:
            turn.thinkMs ?? (turn.thinkStartedAt ? Date.now() - turn.thinkStartedAt : undefined),
          ...(turn.content ? {} : { content: "_Stopped._" }),
        }));
      } else {
        patchTurn(answerId, () => ({
          content: (e as Error).message || "Something went wrong.",
          failed: true,
          streaming: false,
          question: message,
        }));
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setLoading(false);
      onActivity?.();
    }
  };

  const stop = () => abortRef.current?.abort();

  const send = () => {
    const message = input.trim();
    if (!message || loading) return;
    setInput("");
    void ask(message);
  };

  /** Re-ask the question at `index` (edit / regenerate / retry). */
  const reask = (index: number, text: string) => {
    const question = turns[index];
    if (!question || question.role !== "user" || loading) return;
    void ask(text, { index, messageId: question.messageId ?? null });
  };

  const retry = (turn: Turn) => {
    if (!turn.question || loading) return;
    const index = turns.findIndex((item) => item.id === turn.id);
    if (index > 0 && turns[index - 1].role === "user") reask(index - 1, turn.question);
    else void ask(turn.question);
  };

  const changeScope = (next: VaultScope | null) => {
    setScope(next);
    if (!next && contextMode !== "retrieval") setContextMode("retrieval");
  };

  const quizFrom = (index: number) => {
    const turn = turns[index];
    const question = [...turns.slice(0, index)].reverse().find((item) => item.role === "user");
    if (!turn || !onQuiz) return;
    const cited = new Set<string>();
    for (const match of turn.content.matchAll(/\[S(\d+)\]/g)) cited.add(`S${match[1]}`);
    const used = (turn.sources ?? []).filter((source) => !cited.size || cited.has(source.marker));
    const documentIds = [...new Set(used.map((source) => source.document_id).filter((id): id is number => Boolean(id && id > 0)))];
    const courses = used.map((source) => source.course).filter(Boolean) as string[];
    onQuiz({
      question: question?.content ?? "",
      course: courses[0] ?? scope?.course ?? null,
      documentIds,
      notePath: turn.notePath ?? null,
    });
  };

  const tools = (
    <>
      {!noteScope && (
        <SourcesMenu
          scope={scope}
          mode={contextMode}
          onMode={setContextMode}
          docs={docs}
          items={contextItems}
          onToggle={(doc, on) => {
            setDocumentContext(doc, on ? "snippets" : "exclude");
            if (on && contextMode === "retrieval") setContextMode("hybrid");
          }}
          onDocMode={setDocumentContext}
        />
      )}
      {activeNote && (
        <NoteScopeChip note={activeNote} on={noteScopeOn} onToggle={() => setNoteScopeOn((value) => !value)} />
      )}
      {!noteScope && <ScopeMenu scope={scope} scopes={scopes} onChange={changeScope} compact={compact} />}
    </>
  );

  const isEmpty = turns.length === 0 && !loadingHistory && !historyError;
  const lastAssistant = (() => {
    for (let index = turns.length - 1; index >= 0; index--) if (turns[index].role === "assistant") return index;
    return -1;
  })();

  if (isEmpty && !compact) {
    return (
      <div className="chat-view">
        <div className="chat-home">
          <h1 className="greeting">
            <BrandMark size={40} />
            <span>{greeting(userName)}</span>
          </h1>
          <Composer
            value={input}
            onChange={setInput}
            onSend={send}
            busy={loading}
            autoFocus
            textareaRef={textareaRef}
            placeholder="How can I help you study today?"
            tools={tools}
            model={modelMenu}
            onStop={stop}
          />
          <div className="suggestions">
            {SUGGESTIONS.map((item) => (
              <button
                type="button"
                key={item.label}
                className="suggestion"
                onClick={() => {
                  if (item.tab) {
                    onNavigate?.(item.tab);
                    return;
                  }
                  setInput(item.prompt ?? "");
                  window.setTimeout(() => {
                    const el = textareaRef.current;
                    el?.focus();
                    el?.setSelectionRange(el.value.length, el.value.length);
                  }, 0);
                }}
              >
                <Icon name={item.icon} size={15} />
                {item.label}
              </button>
            ))}
          </div>
          {showToday && <TodayNudge onOpen={() => onNavigate?.("today")} />}
          <p className="home-scope-note">
            Answers come only from your own notes, with the sources cited.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={`chat-view${compact ? " compact" : ""}`}>
      {isEmpty ? (
        <div className="dock-empty">
          <BrandMark size={28} />
          <span>
            {noteScope ? (
              <>
                Ask about <strong>{noteScope.title}</strong>.<br />
                Answers use this note and the notes it links to.
              </>
            ) : (
              <>
                Ask anything about your notes.
                <br />
                Answers cite the sources they use.
              </>
            )}
          </span>
        </div>
      ) : (
        <div className="thread" ref={threadRef} onScroll={onThreadScroll}>
          <div className="thread-inner">
            {loadingHistory && <div className="muted small">Loading conversation…</div>}
            {historyError && <div className="warn-banner">{historyError}</div>}
            {turns.map((turn, index) =>
              turn.role === "user" ? (
                <UserTurn
                  key={turn.id}
                  turn={turn}
                  canEdit={!loading && turn.messageId != null}
                  onEdit={(text) => reask(index, text)}
                />
              ) : (
                <AssistantTurn
                  key={turn.id}
                  turn={turn}
                  isLast={index === turns.length - 1}
                  vaultRoot={vaultRoot}
                  onOpenNote={onOpenNote}
                  onRetry={retry}
                  onRegenerate={
                    index === lastAssistant && index > 0 && turns[index - 1].role === "user" && turns[index - 1].messageId != null
                      ? () => reask(index - 1, turns[index - 1].content)
                      : undefined
                  }
                  onQuiz={onQuiz ? () => quizFrom(index) : undefined}
                  busy={loading}
                />
              ),
            )}
          </div>
        </div>
      )}
      <div className="composer-dock">
        <Composer
          value={input}
          onChange={setInput}
          onSend={send}
          busy={loading}
          autoFocus
          textareaRef={textareaRef}
          placeholder={noteScope ? `Ask about ${noteScope.title}…` : compact ? "Ask about your notes…" : "Reply…"}
          tools={tools}
          model={modelMenu}
          onStop={stop}
        />
        {!compact && (
          <p className="chat-foot-note">
            Study Copilot answers from your notes and can still get things wrong. Check the cited sources.
          </p>
        )}
      </div>
    </div>
  );
}
