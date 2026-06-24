import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";
import { api } from "../api";
import type { Citation } from "../types";
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
  const [convId, setConvId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

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
        scope_path: scope?.path ?? null,
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
    <div>
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
