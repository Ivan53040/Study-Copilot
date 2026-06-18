import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { ChatPage } from "./pages/Chat";
import { SearchPage } from "./pages/Search";
import { GeneratePage } from "./pages/Generate";
import { NotesPage } from "./pages/Notes";
import { GraphPage } from "./pages/Graph";
import { LibraryPage } from "./pages/Library";
import { QuizPage } from "./pages/Quiz";
import { ProgressPage } from "./pages/Progress";
import { PlanPage } from "./pages/Plan";
import { PastPapersPage } from "./pages/PastPapers";

type Tab =
  | "notes"
  | "graph"
  | "search"
  | "generate"
  | "quiz"
  | "progress"
  | "plan"
  | "papers"
  | "library";

const TABS: { id: Tab; label: string }[] = [
  { id: "notes", label: "📒  Notes" },
  { id: "graph", label: "🕸️  Graph" },
  { id: "search", label: "🔍  Search" },
  { id: "generate", label: "✍️  Generate" },
  { id: "quiz", label: "🧠  Quiz" },
  { id: "progress", label: "📈  Progress" },
  { id: "plan", label: "🗓️  Daily Plan" },
  { id: "papers", label: "📄  Past Papers" },
  { id: "library", label: "📚  Library" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("notes");
  const [notePath, setNotePath] = useState<string | null>(null);
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth >= 900);
  const [tocOpen, setTocOpen] = useState(() => window.innerWidth >= 1100);
  const [chatOpen, setChatOpen] = useState(false);

  const selectTab = (id: Tab) => {
    setTab(id);
    if (window.innerWidth < 900) setLeftOpen(false); // close drawer on mobile
  };
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);

  const openNote = (path: string) => {
    setNotePath(path);
    setTab("notes");
    if (window.innerWidth < 900) setLeftOpen(false);
  };

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api
        .health()
        .then((h) => alive && (setHealth(h), setOnline(true)))
        .catch(() => alive && setOnline(false));
    ping();
    const t = setInterval(ping, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const current = TABS.find((t) => t.id === tab);

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="icon-btn"
          title="Toggle sidebar"
          onClick={() => setLeftOpen((o) => !o)}
        >
          ☰
        </button>
        <span className="brand">
          Study<span style={{ color: "var(--accent)" }}>Copilot</span>
        </span>
        <span className="muted small">{current?.label}</span>
        <div className="grow" />
        {tab === "notes" && (
          <button
            className={`icon-btn ${tocOpen ? "active" : ""}`}
            title="Toggle outline"
            onClick={() => setTocOpen((o) => !o)}
          >
            ▦
          </button>
        )}
        <button
          className={`icon-btn ${chatOpen ? "active" : ""}`}
          title="Toggle chat panel"
          onClick={() => setChatOpen((o) => !o)}
        >
          💬
        </button>
      </header>

      <div className="app-body">
        {leftOpen && (
          <aside className="sidebar">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`nav-item ${tab === t.id ? "active" : ""}`}
                onClick={() => selectTab(t.id)}
              >
                {t.label}
              </button>
            ))}
            <div className="status">
              <div>
                <span className={`dot ${online ? "ok" : "off"}`} />
                {online ? "Backend online" : "Backend offline"}
              </div>
              {health && (
                <div className="small" style={{ marginTop: 6 }}>
                  model: {health.default_provider}
                  <br />
                  vault: {health.vault_exists ? "ok" : "missing"}
                </div>
              )}
            </div>
          </aside>
        )}

        <main className="main">
          {tab === "notes" && (
            <NotesPage path={notePath} onOpen={openNote} tocOpen={tocOpen} />
          )}
          {tab === "graph" && <GraphPage onOpen={openNote} />}
          {tab === "search" && <SearchPage />}
          {tab === "generate" && <GeneratePage />}
          {tab === "quiz" && <QuizPage />}
          {tab === "progress" && <ProgressPage />}
          {tab === "plan" && <PlanPage />}
          {tab === "papers" && <PastPapersPage />}
          {tab === "library" && <LibraryPage />}
        </main>

        {chatOpen && (
          <aside className="chat-dock">
            <ChatPage />
          </aside>
        )}
      </div>
    </div>
  );
}
