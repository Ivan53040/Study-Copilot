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
import type {
  ChatSource,
  Citation,
  DocumentRow,
  StudySetItem,
  VaultScope,
} from "../types";
import { BrandMark, Icon } from "../icons";
import { SourcePageViewer, TRUST_LABEL, hasPageImage, useDismiss } from "../components";
import { rankScopes, scopeKindLabel, useScopes } from "../CoursePicker";

type ContextMode = "retrieval" | "manual" | "hybrid";

interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  sources?: ChatSource[];
  warnings?: string[];
  failed?: boolean;
  question?: string;
}

export interface ChatPageProps {
  /** Load this saved conversation on mount (null = a new chat). */
  conversationId?: number | null;
  /** Side-panel variant used next to notes and other tools. */
  compact?: boolean;
  userName?: string;
  modelLabel?: string;
  vaultRoot?: string | null;
  onConversationCreated?: (id: number) => void;
  onActivity?: () => void;
  onOpenNote?: (path: string) => void;
  onNavigate?: (tab: string) => void;
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
  modelLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  placeholder: string;
  autoFocus?: boolean;
  textareaRef: RefObject<HTMLTextAreaElement>;
  tools: ReactNode;
  modelLabel?: string;
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
        {modelLabel && <span className="model-label" title="Chat model (change in Settings)">{modelLabel}</span>}
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

function AssistantTurn({
  turn,
  isLast,
  vaultRoot,
  onOpenNote,
  onRetry,
  busy = false,
}: {
  turn: Turn;
  isLast: boolean;
  vaultRoot?: string | null;
  onOpenNote?: (path: string) => void;
  onRetry: (turn: Turn) => void;
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

  const markdown = turn.content.replace(/\[S(\d+)\]/g, '<sup data-cite="S$1">$1</sup>');
  return (
    <div className={`turn turn-assistant${isLast ? " last" : ""}`}>
      <div className="md">
        <ReactMarkdown remarkPlugins={mdRemarkPlugins} rehypePlugins={mdRehypePlugins} components={components}>
          {markdown}
        </ReactMarkdown>
      </div>
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
      {turn.warnings?.map((warning, index) => (
        <div className="turn-warning" key={index}>
          <Icon name="alert-triangle" size={14} />
          <span>{warning}</span>
        </div>
      ))}
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
        {refs.length > 0 && (
          <span className="turn-meta">
            {refs.length} {refs.length === 1 ? "source" : "sources"}
          </span>
        )}
      </div>
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

function Thinking() {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    const timer = window.setTimeout(() => setPhase(1), 1800);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <div className="turn thinking" aria-live="polite">
      <BrandMark size={20} />
      <span className="thinking-text">{phase === 0 ? "Searching your notes…" : "Writing an answer…"}</span>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Page                                                                      */
/* ------------------------------------------------------------------------ */

export function ChatPage({
  conversationId = null,
  compact = false,
  userName = "",
  modelLabel,
  vaultRoot,
  onConversationCreated,
  onActivity,
  onOpenNote,
  onNavigate,
}: ChatPageProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [contextMode, setContextMode] = useState<ContextMode>("retrieval");
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [contextItems, setContextItems] = useState<StudySetItem[]>([]);
  const [convId, setConvId] = useState<number | null>(conversationId);
  const [convCourse, setConvCourse] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(Boolean(conversationId));
  const [historyError, setHistoryError] = useState<string | null>(null);
  const scopes = useScopes();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
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

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, loading, loadingHistory]);

  const setDocumentContext = (doc: DocumentRow, mode: StudySetItem["mode"]) => {
    setContextItems((current) => {
      const rest = current.filter(
        (item) => !(item.kind === "document" && Number(item.ref) === doc.id),
      );
      if (mode === "exclude") return rest;
      return [...rest, { kind: "document", ref: doc.id, mode }];
    });
  };

  const ask = async (message: string) => {
    if (!message || loading) return;
    const contextModeForSend: ContextMode =
      contextMode === "retrieval" || contextItems.length > 0 ? contextMode : "retrieval";
    setTurns((current) => [...current, { id: nextId(), role: "user", content: message }]);
    setLoading(true);
    try {
      const res = await api.chat({
        message,
        course: scope?.course ?? null,
        scope_path: scope?.kind === "study_set" ? null : scope?.path ?? null,
        study_set_id: scope?.study_set_id ?? null,
        context_mode: contextModeForSend,
        context_items: contextItems,
        conversation_id: convId,
      });
      if (res.conversation_id !== convId) {
        setConvId(res.conversation_id);
        // A late reply from a chat the user has already left must not
        // re-select it in the header / sidebar.
        if (mounted.current) onConversationCreated?.(res.conversation_id);
      }
      setTurns((current) => [
        ...current,
        {
          id: nextId(),
          role: "assistant",
          content: res.answer,
          citations: res.citations,
          sources: res.sources,
          warnings: res.warnings,
        },
      ]);
    } catch (e) {
      setTurns((current) => [
        ...current,
        {
          id: nextId(),
          role: "assistant",
          content: (e as Error).message || "Something went wrong.",
          failed: true,
          question: message,
        },
      ]);
    } finally {
      setLoading(false);
      onActivity?.();
    }
  };

  const send = () => {
    const message = input.trim();
    if (!message || loading) return;
    setInput("");
    void ask(message);
  };

  const retry = (turn: Turn) => {
    if (!turn.question || loading) return;
    setTurns((current) => {
      const index = current.findIndex((item) => item.id === turn.id);
      // Drop the failed answer and the question it belonged to; ask() re-adds it.
      return index > 0 ? current.slice(0, index - 1) : current.filter((item) => item.id !== turn.id);
    });
    void ask(turn.question);
  };

  const changeScope = (next: VaultScope | null) => {
    setScope(next);
    if (!next && contextMode !== "retrieval") setContextMode("retrieval");
  };

  const tools = (
    <>
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
      <ScopeMenu scope={scope} scopes={scopes} onChange={changeScope} compact={compact} />
    </>
  );

  const isEmpty = turns.length === 0 && !loading && !loadingHistory && !historyError;

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
            modelLabel={modelLabel}
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
          <span>Ask anything about your notes.<br />Answers cite the sources they use.</span>
        </div>
      ) : (
        <div className="thread" ref={threadRef}>
          <div className="thread-inner">
            {loadingHistory && <div className="muted small">Loading conversation…</div>}
            {historyError && <div className="warn-banner">{historyError}</div>}
            {turns.map((turn, index) =>
              turn.role === "user" ? (
                <div key={turn.id} className="turn turn-user">
                  {turn.content}
                </div>
              ) : (
                <AssistantTurn
                  key={turn.id}
                  turn={turn}
                  isLast={index === turns.length - 1 && !loading}
                  vaultRoot={vaultRoot}
                  onOpenNote={onOpenNote}
                  onRetry={retry}
                  busy={loading}
                />
              ),
            )}
            {loading && <Thinking />}
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
          placeholder={compact ? "Ask about your notes…" : "Reply…"}
          tools={tools}
          modelLabel={modelLabel}
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
