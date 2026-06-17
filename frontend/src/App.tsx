import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { ChatPage } from "./pages/Chat";
import { SearchPage } from "./pages/Search";
import { NotesPage } from "./pages/Notes";
import { LibraryPage } from "./pages/Library";

type Tab = "chat" | "search" | "notes" | "library";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "💬  Chat" },
  { id: "search", label: "🔍  Search" },
  { id: "notes", label: "📝  Generate Notes" },
  { id: "library", label: "📚  Library" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState<boolean>(false);

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
        {tab === "chat" && <ChatPage />}
        {tab === "search" && <SearchPage />}
        {tab === "notes" && <NotesPage />}
        {tab === "library" && <LibraryPage />}
      </main>
    </div>
  );
}
