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
  | "chat"
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
  { id: "chat", label: "💬  Chat" },
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
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState<boolean>(false);

  const openNote = (path: string) => {
    setNotePath(path);
    setTab("notes");
  };

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api
        .health()
        .then((h) => {
          if (alive) {
            setHealth(h);
            setOnline(true);
          }
        })
        .catch(() => alive && setOnline(false));
    ping();
    const t = setInterval(ping, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          Study<span>Copilot</span>
        </div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`nav-item ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
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

      <main className="main">
        {tab === "notes" && <NotesPage path={notePath} onOpen={openNote} />}
        {tab === "graph" && <GraphPage onOpen={openNote} />}
        {tab === "chat" && <ChatPage />}
        {tab === "search" && <SearchPage />}
        {tab === "generate" && <GeneratePage />}
        {tab === "quiz" && <QuizPage />}
        {tab === "progress" && <ProgressPage />}
        {tab === "plan" && <PlanPage />}
        {tab === "papers" && <PastPapersPage />}
        {tab === "library" && <LibraryPage />}
      </main>
    </div>
  );
}
