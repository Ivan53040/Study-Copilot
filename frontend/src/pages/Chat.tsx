import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";
import { api } from "../api";
import type { Citation, DocumentRow, StudySetItem } from "../types";
import { CitationLine, Warnings } from "../components";
import { CoursePicker } from "../CoursePicker";
import type { VaultScope } from "../types";

interface Turn {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  warnings?: string[];
}

export function ChatPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [contextMode, setContextMode] = useState<"retrieval" | "manual" | "hybrid">("retrieval");
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [contextItems, setContextItems] = useState<StudySetItem[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDocs([]);
    setContextItems([]);
    if (!scope || scope.kind === "study_set") return;
    api
      .scopeDocuments(scope.path)
      .then((result) => setDocs(result.documents))
      .catch(() => {});
  }, [scope]);

  const includedCount = contextItems.filter((item) => item.mode !== "exclude").length;
  const approxTokens = useMemo(() => {
    const selectedIds = new Set(
      contextItems
        .filter((item) => item.kind === "document" && item.mode !== "exclude")
        .map((item) => Number(item.ref)),
    );
    return docs
      .filter((doc) => selectedIds.has(doc.id))
      .reduce((total, doc) => total + doc.chunks * 220, 0);
  }, [contextItems, docs]);

  const setDocumentContext = (doc: DocumentRow, mode: StudySetItem["mode"]) => {
    setContextItems((current) => {
      const rest = current.filter(
        (item) => !(item.kind === "document" && Number(item.ref) === doc.id),
      );
      if (mode === "exclude") return rest;
      return [...rest, { kind: "document", ref: doc.id, mode }];
    });
  };

  const contextModeForSend =
    contextMode === "retrieval" || contextItems.length > 0 ? contextMode : "retrieval";

  const send = async () => {
    const message = input.trim();
    if (!message || loading) return;
    setError(null);
    setInput("");
    setTurns((t) => [...t, { role: "user", content: message }]);
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
      setConvId(res.conversation_id);
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: res.answer,
          citations: res.citations,
          warnings: res.warnings,
        },
      ]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  };

  return (
    <div className="chat-page">
      <h1 className="page-title">Chat</h1>
      <p className="page-sub">
        Grounded Q&amp;A over your notes — answers cite the sources they come from.
      </p>

      <div className="row" style={{ marginBottom: 12 }}>
        <label className="small muted">Course</label>
        <div className="chat-course-picker">
          <CoursePicker
            value={scope}
            onChange={(selected) => {
              setScope(selected);
              setTurns([]);
              setConvId(null);
            }}
          />
        </div>
        <button
          onClick={() => {
            setTurns([]);
            setConvId(null);
          }}
        >
          New conversation
        </button>
        {convId && <span className="small muted">conversation #{convId}</span>}
      </div>

      <div className="context-panel card">
        <div className="context-panel-head">
          <div>
            <strong>Context</strong>
            <span className="small muted">
              {includedCount} selected
              {approxTokens ? ` · about ${approxTokens.toLocaleString()} tokens` : ""}
            </span>
          </div>
          <select
            value={contextMode}
            onChange={(event) => setContextMode(event.target.value as typeof contextMode)}
          >
            <option value="retrieval">Retrieval</option>
            <option value="manual">Manual</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </div>
        {scope?.kind === "study_set" ? (
          <div className="small muted">This study set supplies its saved context.</div>
        ) : docs.length ? (
          <div className="context-list">
            {docs.map((doc) => {
              const item = contextItems.find(
                (candidate) =>
                  candidate.kind === "document" && Number(candidate.ref) === doc.id,
              );
              return (
                <label className="context-row" key={doc.id}>
                  <input
                    type="checkbox"
                    checked={Boolean(item)}
                    onChange={(event) =>
                      setDocumentContext(doc, event.target.checked ? "snippets" : "exclude")
                    }
                  />
                  <span title={doc.title}>{doc.title}</span>
                  <select
                    value={item?.mode ?? "snippets"}
                    disabled={!item}
                    onChange={(event) =>
                      setDocumentContext(doc, event.target.value as StudySetItem["mode"])
                    }
                  >
                    <option value="snippets">Snippets</option>
                    <option value="full">Full</option>
                  </select>
                </label>
              );
            })}
          </div>
        ) : (
          <div className="small muted">Pick a course or folder to choose manual context.</div>
        )}
      </div>

      <div className="chat-wrap">
        <div className="messages">
          {turns.length === 0 && (
            <div className="muted">
              Ask something like “What is the difference between reliability and
              validity?”
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={`msg ${t.role}`}>
              <div className="md">
                <ReactMarkdown
                  remarkPlugins={mdRemarkPlugins}
                  rehypePlugins={mdRehypePlugins}
                  components={mdComponents}
                >
                  {t.content}
                </ReactMarkdown>
              </div>
              {t.citations && t.citations.length > 0 && (
                <div className="citations">
                  {t.citations.map((c, j) => (
                    <CitationLine key={j} cite={c} />
                  ))}
                </div>
              )}
              {t.warnings && <Warnings items={t.warnings} />}
            </div>
          ))}
          {loading && <div className="msg assistant spinner">Thinking…</div>}
          <div ref={endRef} />
        </div>

        {error && <div className="warn-banner">{error}</div>}

        <div className="chat-input">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask your notes… (Enter to send, Shift+Enter for newline)"
          />
          <button className="primary" onClick={send} disabled={loading}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
