import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { Icon } from "./icons";
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

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "notes", label: "Notes", icon: "file-text" },
  { id: "graph", label: "Graph", icon: "graph" },
  { id: "search", label: "Search", icon: "search" },
  { id: "generate", label: "Generate", icon: "pencil" },
  { id: "quiz", label: "Quiz", icon: "graduation-cap" },
  { id: "progress", label: "Progress", icon: "trending-up" },
  { id: "plan", label: "Plan", icon: "calendar" },
  { id: "papers", label: "Past Papers", icon: "layers" },
  { id: "library", label: "Library", icon: "book" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("notes");
  const [notePath, setNotePath] = useState<string | null>(null);
  const [treeOpen, setTreeOpen] = useState(() => window.innerWidth >= 900);
  const [tocOpen, setTocOpen] = useState(() => window.innerWidth >= 1100);
  const [chatOpen, setChatOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);

  const openNote = (path: string) => {
    setNotePath(path);
    setTab("notes");
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

  const isNotes = tab === "notes";

  return (
    <div className="app-shell">
      <header className="topbar">
        {isNotes && (
          <button
            className={`icon-btn ${treeOpen ? "active" : ""}`}
            title="Toggle file tree"
            onClick={() => setTreeOpen((o) => !o)}
          >
            <Icon name="panel-left" size={17} />
          </button>
        )}
        <span className="brand">
          Study<span style={{ color: "var(--accent)" }}>Copilot</span>
        </span>

        <nav className="topnav">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`nav-btn ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
              title={t.label}
            >
              <Icon name={t.icon} size={16} />
              <span className="nav-label">{t.label}</span>
            </button>
          ))}
        </nav>

        <div className="grow" />

        <span className="topstatus" title={health ? `model: ${health.default_provider} · vault: ${health.vault_exists ? "ok" : "missing"}` : ""}>
          <span className={`dot ${online ? "ok" : "off"}`} />
          <span className="status-text">{online ? "online" : "offline"}</span>
        </span>
        {isNotes && (
          <button
            className={`icon-btn ${tocOpen ? "active" : ""}`}
            title="Toggle outline"
            onClick={() => setTocOpen((o) => !o)}
          >
            <Icon name="panel-right" size={17} />
          </button>
        )}
        <button
          className={`icon-btn ${chatOpen ? "active" : ""}`}
          title="Toggle chat panel"
          onClick={() => setChatOpen((o) => !o)}
        >
          <Icon name="message-square" size={17} />
        </button>
      </header>

      <div className="app-body">
        <main className="main">
          {tab === "notes" && (
            <NotesPage
              path={notePath}
              onOpen={openNote}
              tocOpen={tocOpen}
              treeOpen={treeOpen}
            />
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
