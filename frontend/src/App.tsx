import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { Icon } from "./icons";
import { ChatPage } from "./pages/Chat";
import { SearchPage } from "./pages/Search";
import { GeneratePage } from "./pages/Generate";
import { NotesPage } from "./pages/Notes";
import { GraphPage } from "./pages/Graph";
import { LibraryPage } from "./pages/Library";
import { LecturesPage } from "./pages/Lectures";
import { QuizPage } from "./pages/Quiz";
import { ProgressPage } from "./pages/Progress";
import { PlanPage } from "./pages/Plan";
import { PastPapersPage } from "./pages/PastPapers";
import { SettingsPage, applyAppearance, loadAppearance } from "./pages/Settings";

type Tab =
  | "notes"
  | "lectures"
  | "graph"
  | "search"
  | "generate"
  | "quiz"
  | "progress"
  | "plan"
  | "papers"
  | "library"
  | "settings";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "notes", label: "Notes", icon: "file-text" },
  { id: "lectures", label: "Lecture Materials", icon: "layers" },
  { id: "plan", label: "Plan", icon: "calendar" },
  { id: "search", label: "Search", icon: "search" },
  { id: "graph", label: "Graph", icon: "graph" },
  { id: "generate", label: "Generate", icon: "pencil" },
  { id: "quiz", label: "Quiz", icon: "graduation-cap" },
  { id: "progress", label: "Progress", icon: "trending-up" },
  { id: "papers", label: "Past Papers", icon: "layers" },
  { id: "library", label: "Library", icon: "book" },
  { id: "settings", label: "Settings", icon: "settings" },
];

// Top-bar quick switcher: type to find a note and open it.
function QuickOpen({ onOpen }: { onOpen: (path: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ path: string; title: string }[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    let alive = true;
    api
      .vaultSearch(q)
      .then((r) => alive && setResults(r.results.slice(0, 8)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [q]);

  return (
    <div className="quickopen">
      <Icon name="search" size={14} />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Quick open note…"
      />
      {open && results.length > 0 && (
        <div className="quickopen-menu">
          {results.map((r) => (
            <div
              key={r.path}
              className="quickopen-item"
              onMouseDown={() => {
                onOpen(r.path);
                setQ("");
                setOpen(false);
              }}
            >
              <div>{r.title}</div>
              <div className="muted small">{r.path}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function App() {
  const query = new URLSearchParams(window.location.search);
  const detached = query.get("detached") === "1";
  const [tab, setTab] = useState<Tab>("notes");
  const [notePath, setNotePath] = useState<string | null>(
    () => query.get("note"),
  );
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth >= 900);
  const [treeOpen, setTreeOpen] = useState(() => window.innerWidth >= 1000);
  const [tocOpen, setTocOpen] = useState(() => window.innerWidth >= 1200);
  const [chatOpen, setChatOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);
  const [vaultRevision, setVaultRevision] = useState(0);
  const lastWidth = useRef(window.innerWidth);

  const refreshHealth = () =>
    api
      .health()
      .then((h) => (setHealth(h), setOnline(true)))
      .catch(() => setOnline(false));

  const selectTab = (id: Tab) => {
    setTab(id);
    if (window.innerWidth < 900) setLeftOpen(false);
  };
  const openNote = useCallback((path: string) => {
    setNotePath(path);
    setTab("notes");
    if (window.innerWidth < 900) setLeftOpen(false);
  }, []);

  useEffect(() => {
    applyAppearance(loadAppearance());
  }, []);

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

  // Re-open panels when the window grows back to a comfortable width.
  useEffect(() => {
    const onResize = () => {
      const w = window.innerWidth;
      if (w > lastWidth.current) {
        if (w >= 900) setLeftOpen(true);
        if (w >= 1000) setTreeOpen(true);
        if (w >= 1200) setTocOpen(true);
      }
      lastWidth.current = w;
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const isNotes = tab === "notes";
  const current = TABS.find((t) => t.id === tab);
  const title = isNotes && notePath ? notePath : current?.label ?? "";

  if (detached) {
    return (
      <div className="detached-shell">
        <main className="main detached-main">
          <NotesPage
            path={notePath}
            tocOpen={false}
            treeOpen={false}
            detached
          />
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className={`icon-btn ${leftOpen ? "active" : ""}`}
          title="Toggle sidebar"
          onClick={() => setLeftOpen((o) => !o)}
        >
          <Icon name="menu" size={17} />
        </button>
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
        <span className="crumb muted">{title}</span>

        <div className="grow" />

        <QuickOpen onOpen={openNote} />

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
        <aside className={`sidebar ${leftOpen ? "open" : ""}`}>
          {leftOpen && (
            <>
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`nav-item ${tab === t.id ? "active" : ""}`}
                onClick={() => selectTab(t.id)}
              >
                <Icon name={t.icon} size={16} />
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
            </>
          )}
        </aside>

        <main className="main">
          {tab === "notes" && (
            <NotesPage key={vaultRevision} path={notePath} tocOpen={tocOpen} treeOpen={treeOpen} />
          )}
          {tab === "lectures" && <LecturesPage />}
          {tab === "graph" && <GraphPage onOpen={openNote} />}
          {tab === "search" && <SearchPage />}
          {tab === "generate" && <GeneratePage />}
          {tab === "quiz" && <QuizPage />}
          {tab === "progress" && <ProgressPage />}
          {tab === "plan" && <PlanPage />}
          {tab === "papers" && <PastPapersPage />}
          {tab === "library" && <LibraryPage />}
          {tab === "settings" && (
            <SettingsPage
              onSaved={() => {
                setVaultRevision((value) => value + 1);
                refreshHealth();
              }}
            />
          )}
        </main>

        <aside className={`chat-dock ${chatOpen ? "open" : ""}`}>
          {chatOpen && <ChatPage />}
        </aside>
      </div>
    </div>
  );
}
