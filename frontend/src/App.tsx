import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { AppSettings, ConversationSummary, Health } from "./types";
import { BrandMark, Icon } from "./icons";
import { useDismiss } from "./components";
import { ChatPage, type QuizFromAnswer } from "./pages/Chat";
import type { QuizPreset } from "./pages/Quiz";
import { loadMarkdownExtras, onMarkdownExtrasReady } from "./markdown";
import { type Appearance, loadAppearance } from "./theme";

// Chat (the home screen) ships in the main bundle; every other page is its own
// chunk, loaded on first visit. The notes workspace (the heaviest: editor,
// graph) is prefetched once the app is idle so opening it stays instant.
const loadNotes = () => import("./pages/Notes");
const NotesPage = lazy(() => loadNotes().then((m) => ({ default: m.NotesPage })));
const SearchPage = lazy(() => import("./pages/Search").then((m) => ({ default: m.SearchPage })));
const GeneratePage = lazy(() => import("./pages/Generate").then((m) => ({ default: m.GeneratePage })));
const WikiPage = lazy(() => import("./pages/Wiki").then((m) => ({ default: m.WikiPage })));
const VoiceNotesPage = lazy(() => import("./pages/VoiceNotes").then((m) => ({ default: m.VoiceNotesPage })));
const LibraryPage = lazy(() => import("./pages/Library").then((m) => ({ default: m.LibraryPage })));
const LecturesPage = lazy(() => import("./pages/Lectures").then((m) => ({ default: m.LecturesPage })));
const QuizPage = lazy(() => import("./pages/Quiz").then((m) => ({ default: m.QuizPage })));
const ProgressPage = lazy(() => import("./pages/Progress").then((m) => ({ default: m.ProgressPage })));
const PlanPage = lazy(() => import("./pages/Plan").then((m) => ({ default: m.PlanPage })));
const PastPapersPage = lazy(() => import("./pages/PastPapers").then((m) => ({ default: m.PastPapersPage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));
const TodayPage = lazy(() => import("./pages/Today").then((m) => ({ default: m.TodayPage })));

function PageLoading() {
  return (
    <div className="page-loading" aria-busy="true">
      <BrandMark size={22} />
    </div>
  );
}

type Tab =
  | "chat"
  | "today"
  | "notes"
  | "lectures"
  | "voice"
  | "wiki"
  | "search"
  | "generate"
  | "quiz"
  | "progress"
  | "plan"
  | "papers"
  | "library"
  | "settings";

type NavItem = { id: Tab; label: string; icon: string };

const WORKSPACE_NAV: NavItem[] = [
  { id: "today", label: "Today", icon: "sun" },
  { id: "notes", label: "Notes", icon: "file-text" },
  { id: "lectures", label: "Lecture materials", icon: "layers" },
  { id: "voice", label: "Voice notes", icon: "mic" },
  { id: "wiki", label: "Wiki", icon: "book" },
];

const STUDY_NAV: NavItem[] = [
  { id: "quiz", label: "Quiz", icon: "graduation-cap" },
  { id: "plan", label: "Daily plan", icon: "calendar" },
  { id: "progress", label: "Progress", icon: "trending-up" },
  { id: "papers", label: "Past papers", icon: "target" },
  { id: "search", label: "Source search", icon: "search" },
  { id: "generate", label: "Generate", icon: "sparkles" },
  { id: "library", label: "Library", icon: "library" },
];

const ALL_NAV: NavItem[] = [
  { id: "chat", label: "New chat", icon: "message-circle" },
  ...WORKSPACE_NAV,
  ...STUDY_NAV,
  { id: "settings", label: "Settings", icon: "settings" },
];

const FRAMED: Tab[] = ["search", "generate", "quiz", "progress", "plan", "papers", "library", "settings"];

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = isMac ? "⌘" : "Ctrl";

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (!list) return;
    const onChange = () => setMatches(list.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

function readBool(key: string, fallback: boolean) {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : value === "1";
  } catch {
    return fallback;
  }
}
function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function modelLabelFrom(settings: AppSettings | null, health: Health | null): string | undefined {
  const override = settings?.task_models?.chat;
  const provider = override?.provider || settings?.default_provider || health?.default_provider;
  if (!provider) return undefined;
  if (override?.model) return override.model;
  if (provider === "echo") return "Offline echo";
  const model =
    provider === "openai"
      ? settings?.openai_model
      : provider === "anthropic"
        ? settings?.anthropic_model
        : settings?.llm_model;
  if (model && model !== "local-model") return model;
  return provider === "lmstudio" ? "LM Studio" : provider === "openai" ? "OpenAI" : "Anthropic";
}

/* ------------------------------------------------------------------------ */
/* Quick open (Ctrl/⌘+K)                                                     */
/* ------------------------------------------------------------------------ */

type QuickItem =
  | { kind: "note"; key: string; title: string; sub: string; path: string }
  | { kind: "chat"; key: string; title: string; sub: string; id: number }
  | { kind: "page"; key: string; title: string; sub: string; tab: Tab; icon: string };

function QuickOpen({
  recents,
  onClose,
  onOpenNote,
  onOpenChat,
  onOpenTab,
}: {
  recents: ConversationSummary[];
  onClose: () => void;
  onOpenNote: (path: string) => void;
  onOpenChat: (id: number) => void;
  onOpenTab: (tab: Tab) => void;
}) {
  const [q, setQ] = useState("");
  const [notes, setNotes] = useState<{ path: string; title: string }[]>([]);
  const [focus, setFocus] = useState(0);

  useEffect(() => {
    if (!q.trim()) {
      setNotes([]);
      return;
    }
    let alive = true;
    const timer = window.setTimeout(() => {
      api
        .vaultSearch(q)
        .then((r) => alive && setNotes(r.results.slice(0, 8)))
        .catch(() => {});
    }, 120);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [q]);

  const items: QuickItem[] = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const chats = recents
      .filter((c) => !needle || c.title.toLowerCase().includes(needle) || c.preview.toLowerCase().includes(needle))
      .slice(0, needle ? 5 : 6)
      .map<QuickItem>((c) => ({ kind: "chat", key: `c${c.id}`, title: c.title, sub: c.course ?? "Chat", id: c.id }));
    const pages = ALL_NAV.filter((n) => !needle || n.label.toLowerCase().includes(needle))
      .slice(0, needle ? 4 : 0)
      .map<QuickItem>((n) => ({ kind: "page", key: `p${n.id}`, title: n.label, sub: "Go to", tab: n.id, icon: n.icon }));
    const noteItems = notes.map<QuickItem>((n) => ({
      kind: "note",
      key: `n${n.path}`,
      title: n.title,
      sub: n.path.split("/").slice(0, -1).join(" / ") || "Vault",
      path: n.path,
    }));
    return [...noteItems, ...pages, ...chats];
  }, [q, notes, recents]);

  useEffect(() => setFocus(0), [q]);

  const run = (item: QuickItem | undefined) => {
    if (!item) return;
    if (item.kind === "note") onOpenNote(item.path);
    else if (item.kind === "chat") onOpenChat(item.id);
    else onOpenTab(item.tab);
    onClose();
  };

  let lastKind: string | null = null;
  return (
    <div className="qo-backdrop" onMouseDown={onClose}>
      <div className="qo-panel" role="dialog" aria-label="Quick open" onMouseDown={(e) => e.stopPropagation()}>
        <div className="qo-input-row">
          <Icon name="search" size={17} />
          <input
            autoFocus
            value={q}
            placeholder="Search notes, chats and pages…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              else if (e.key === "ArrowDown") {
                e.preventDefault();
                setFocus((f) => Math.min(f + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setFocus((f) => Math.max(f - 1, 0));
              } else if (e.key === "Enter" && !e.nativeEvent.isComposing) run(items[focus]);
            }}
          />
        </div>
        <div className="qo-results">
          {items.map((item, index) => {
            const heading =
              item.kind !== lastKind
                ? item.kind === "note"
                  ? "Notes"
                  : item.kind === "page"
                    ? "Pages"
                    : q.trim()
                      ? "Chats"
                      : "Recent chats"
                : null;
            lastKind = item.kind;
            return (
              <div key={item.key}>
                {heading && <div className="popover-label">{heading}</div>}
                <button
                  type="button"
                  className={`popover-item${index === focus ? " focus" : ""}`}
                  onMouseEnter={() => setFocus(index)}
                  onClick={() => run(item)}
                >
                  <Icon
                    name={item.kind === "note" ? "file-text" : item.kind === "chat" ? "message-circle" : item.icon}
                    size={16}
                  />
                  <span className="grow">
                    {item.title}
                    <br />
                    <small>{item.sub}</small>
                  </span>
                </button>
              </div>
            );
          })}
          {!items.length && (
            <div className="popover-empty">{q.trim() ? "Nothing found." : "Type to search your vault."}</div>
          )}
        </div>
        <div className="qo-hint">↑↓ to move · Enter to open · Esc to close</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Sidebar                                                                   */
/* ------------------------------------------------------------------------ */

function RecentItem({
  convo,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  convo: ConversationSummary;
  active: boolean;
  onOpen: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [menu, setMenu] = useState<{ top: number; left: number } | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(convo.title);
  const wrap = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  useDismiss(Boolean(menu), () => setMenu(null), [wrap, pop]);

  const toggleMenu = (button: HTMLElement) => {
    if (menu) {
      setMenu(null);
      return;
    }
    // Fixed position so the scrolling sidebar can't clip it; flip up near the bottom.
    const rect = button.getBoundingClientRect();
    const height = 92;
    const top = rect.bottom + height + 8 > window.innerHeight ? rect.top - height - 4 : rect.bottom + 4;
    setMenu({ top, left: Math.max(8, rect.right - 180) });
  };

  if (editing) {
    return (
      <div className="sb-recent">
        <input
          className="sb-rename"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            setEditing(false);
            if (draft.trim() !== convo.title) onRename(draft);
          }}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") {
              setDraft(convo.title);
              setEditing(false);
            }
          }}
        />
      </div>
    );
  }

  return (
    <div className="sb-recent" ref={wrap}>
      <button
        type="button"
        className={`sb-item${active ? " active" : ""}`}
        title={convo.title}
        onClick={onOpen}
      >
        <span className="sb-label">{convo.title}</span>
      </button>
      <button
        type="button"
        className={`sb-item-menu${menu ? " open" : ""}`}
        aria-label={`More options for ${convo.title}`}
        onClick={(event) => toggleMenu(event.currentTarget)}
      >
        <Icon name="more-vertical" size={15} />
      </button>
      {menu && (
        <div
          ref={pop}
          className="popover"
          style={{ position: "fixed", top: menu.top, left: menu.left, width: 180, minWidth: 180 }}
        >
          <button
            type="button"
            className="popover-item"
            onClick={() => {
              setMenu(null);
              setDraft(convo.title);
              setEditing(true);
            }}
          >
            <Icon name="pencil" size={15} /> Rename
          </button>
          <button
            type="button"
            className="popover-item danger"
            onClick={() => {
              setMenu(null);
              onDelete();
            }}
          >
            <Icon name="trash" size={15} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* App                                                                       */
/* ------------------------------------------------------------------------ */

const noteName = (path: string) => (path.split("/").pop() ?? path).replace(/\.(md|markdown|txt)$/i, "");

export function App() {
  const query = new URLSearchParams(window.location.search);
  const detached = query.get("detached") === "1";
  const [tab, setTab] = useState<Tab>(() => (query.get("note") ? "notes" : "chat"));
  const [notePath, setNotePath] = useState<string | null>(() => query.get("note"));
  const [noteOpenSeq, setNoteOpenSeq] = useState(0);
  // The note shown in the notes workspace's active tab (for crumbs + chat scope).
  const [activeNotePath, setActiveNotePath] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(() => readBool("sc.sidebar.collapsed", false));
  const [mobileNav, setMobileNav] = useState(false);
  const isNarrow = useMediaQuery("(max-width: 900px)");
  // The icon rail is a desktop affordance; on narrow windows the sidebar is a drawer.
  const railOnly = collapsed && !isNarrow;
  const [studyOpen, setStudyOpen] = useState(() => readBool("sc.sidebar.study", true));
  const [treeOpen, setTreeOpen] = useState(() => window.innerWidth >= 1000);
  const [tocOpen, setTocOpen] = useState(() => window.innerWidth >= 1280);
  const [dockOpen, setDockOpen] = useState(false);
  // Like the notes pane, chats stay mounted once shown so an answer keeps
  // streaming (and its scroll position) while you look at something else.
  const [dockMounted, setDockMounted] = useState(false);
  useEffect(() => {
    if (dockOpen) setDockMounted(true);
  }, [dockOpen]);
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [appearance, setAppearance] = useState<Appearance>(loadAppearance);
  const [vaultRevision, setVaultRevision] = useState(0);
  // Once opened, the notes workspace stays mounted (hidden) like Obsidian's
  // panes, so returning to it is instant: no tree / note / backlinks refetch.
  const [notesMounted, setNotesMounted] = useState(() => tab === "notes");
  useEffect(() => {
    if (tab === "notes") setNotesMounted(true);
  }, [tab]);
  const [recents, setRecents] = useState<ConversationSummary[]>([]);
  const [chatConvId, setChatConvId] = useState<number | null>(null);
  const [chatKey, setChatKey] = useState(0);
  // Text to start a new chat with (from "Ask" on the Today page).
  const [chatDraft, setChatDraft] = useState("");
  const [quizPreset, setQuizPreset] = useState<QuizPreset | null>(null);
  const [dockConvId, setDockConvId] = useState<number | null>(null);
  const [dockKey, setDockKey] = useState(0);
  const [quickOpen, setQuickOpen] = useState(false);
  const [titleEdit, setTitleEdit] = useState<string | null>(null);
  const [titleMenu, setTitleMenu] = useState(false);
  const titleWrap = useRef<HTMLDivElement>(null);
  useDismiss(titleMenu, () => setTitleMenu(false), [titleWrap]);

  const refreshRecents = useCallback(() => {
    api
      .conversations(40)
      .then((r) => setRecents(r.conversations))
      .catch(() => {});
  }, []);

  const refreshSettings = useCallback(() => {
    api.settings().then(setSettings).catch(() => {});
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

  // Warm the notes workspace chunk once the app is idle.
  useEffect(() => {
    const timer = window.setTimeout(() => void loadNotes().catch(() => {}), 1500);
    return () => window.clearTimeout(timer);
  }, []);

  // Math + code highlighting arrive a moment after start-up; re-render once
  // they do so anything already on screen picks them up.
  const [, setMarkdownExtras] = useState(0);
  useEffect(() => {
    const unsubscribe = onMarkdownExtrasReady(() => setMarkdownExtras((value) => value + 1));
    const timer = window.setTimeout(() => void loadMarkdownExtras().catch(() => {}), 300);
    return () => {
      unsubscribe();
      window.clearTimeout(timer);
    };
  }, []);

  // The packaged backend can take a while on first launch: refetch once online.
  useEffect(() => {
    if (!online) return;
    refreshRecents();
    refreshSettings();
  }, [online, refreshRecents, refreshSettings]);

  const closeMobile = () => {
    if (window.innerWidth <= 900) setMobileNav(false);
  };

  const selectTab = (id: Tab) => {
    setTab(id);
    closeMobile();
  };

  const newChat = useCallback((draft = "") => {
    setChatConvId(null);
    setChatDraft(draft);
    setChatKey((k) => k + 1);
    setTab("chat");
    if (window.innerWidth <= 900) setMobileNav(false);
  }, []);

  const startQuiz = useCallback((request: { topic: string; course: string | null; documentIds?: number[]; origin?: string }) => {
    setQuizPreset({ key: Date.now(), ...request });
    setTab("quiz");
    if (window.innerWidth <= 900) setMobileNav(false);
  }, []);

  const quizFromAnswer = useCallback(
    (request: QuizFromAnswer) =>
      startQuiz({
        topic: request.question || "this answer",
        course: request.course,
        documentIds: request.documentIds,
        origin: `A short quiz on the sources behind: “${request.question.slice(0, 120)}${request.question.length > 120 ? "…" : ""}”`,
      }),
    [startQuiz],
  );

  const openChat = useCallback((id: number) => {
    setChatConvId(id);
    setChatKey((k) => k + 1);
    setTab("chat");
    if (window.innerWidth <= 900) setMobileNav(false);
  }, []);

  const openNote = useCallback((path: string) => {
    setNotePath(path);
    setNoteOpenSeq((value) => value + 1);
    setTab("notes");
    if (window.innerWidth <= 900) setMobileNav(false);
  }, []);

  const renameChat = async (id: number, title: string) => {
    setRecents((list) => list.map((c) => (c.id === id ? { ...c, title: title.trim() || c.title } : c)));
    try {
      await api.renameConversation(id, title);
    } finally {
      refreshRecents();
    }
  };

  const deleteChat = async (id: number) => {
    const convo = recents.find((c) => c.id === id);
    if (!window.confirm(`Delete “${convo?.title ?? "this chat"}”? This can't be undone.`)) return;
    await api.deleteConversation(id).catch(() => {});
    if (chatConvId === id) newChat();
    if (dockConvId === id) {
      setDockConvId(null);
      setDockKey((k) => k + 1);
    }
    refreshRecents();
  };

  // Keyboard shortcuts: Ctrl/⌘+K quick open, Ctrl/⌘+Shift+O new chat.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && !event.shiftKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuickOpen((open) => !open);
      } else if (mod && event.shiftKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        newChat();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat]);

  const dockNotePath =
    tab === "notes" && activeNotePath && /\.(md|markdown|txt)$/i.test(activeNotePath) ? activeNotePath : null;
  const dockNote = useMemo(
    () => (dockNotePath ? { path: dockNotePath, title: noteName(dockNotePath) } : null),
    [dockNotePath],
  );

  const modelLabel = modelLabelFrom(settings, health);
  const vaultRoot = health?.vault_root ?? settings?.vault_root ?? null;
  const activeChat = tab === "chat" && chatConvId ? recents.find((c) => c.id === chatConvId) : undefined;

  if (detached) {
    return (
      <div className="detached-shell">
        <main className="main detached-main">
          <Suspense fallback={<PageLoading />}>
            <NotesPage path={notePath} tocOpen={false} treeOpen={false} detached />
          </Suspense>
        </main>
      </div>
    );
  }

  const navButton = (item: NavItem) => (
    <button
      key={item.id}
      type="button"
      className={`sb-item${tab === item.id ? " active" : ""}`}
      title={railOnly ? item.label : undefined}
      onClick={() => selectTab(item.id)}
    >
      <Icon name={item.icon} size={17} />
      <span className="sb-label">{item.label}</span>
    </button>
  );

  const current = ALL_NAV.find((n) => n.id === tab);
  const shownNote = activeNotePath ?? notePath;
  const noteCrumbs = shownNote ? shownNote.replace(/\.md$/i, "").split("/") : [];


  return (
    <div className="app-shell">
      {mobileNav && <div className="sidebar-scrim" onClick={() => setMobileNav(false)} />}
      <aside className={`sidebar${railOnly ? " collapsed" : ""}${mobileNav ? " mobile-open" : ""}`}>
        <div className="sb-head">
          <button type="button" className="sb-brand" onClick={() => newChat()} title="New chat">
            <BrandMark size={20} className="brand-mark" />
            Study Copilot
          </button>
          <button
            type="button"
            className="icon-btn collapse-toggle"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() =>
              setCollapsed((value) => {
                writeBool("sc.sidebar.collapsed", !value);
                return !value;
              })
            }
          >
            <Icon name="panel-left" size={18} />
          </button>
        </div>

        <nav className="sb-scroll" aria-label="Main">
          <div className="sb-group">
            <button
              type="button"
              className="sb-item sb-new"
              title={railOnly ? `New chat (${MOD}+Shift+O)` : undefined}
              onClick={() => newChat()}
            >
              <span className="sb-new-icon"><Icon name="plus" size={15} /></span>
              <span className="sb-label">New chat</span>
            </button>
            <button
              type="button"
              className="sb-item"
              title={railOnly ? `Search (${MOD}+K)` : undefined}
              onClick={() => setQuickOpen(true)}
            >
              <Icon name="search" size={17} />
              <span className="sb-label">Search</span>
              <span className="sb-kbd">{MOD} K</span>
            </button>
            {WORKSPACE_NAV.map(navButton)}
          </div>

          <button
            type="button"
            className={`sb-section${studyOpen ? "" : " closed"}`}
            onClick={() =>
              setStudyOpen((value) => {
                writeBool("sc.sidebar.study", !value);
                return !value;
              })
            }
          >
            Study tools <Icon name="chevron-down" size={13} />
          </button>
          {(studyOpen || railOnly) && <div className="sb-group">{STUDY_NAV.map(navButton)}</div>}

          <div className="sb-recents">
            <div className="sb-section" style={{ cursor: "default" }}>Recents</div>
            <div className="sb-group">
              {recents.map((convo) => (
                <RecentItem
                  key={convo.id}
                  convo={convo}
                  active={tab === "chat" && chatConvId === convo.id}
                  onOpen={() => openChat(convo.id)}
                  onRename={(title) => void renameChat(convo.id, title)}
                  onDelete={() => void deleteChat(convo.id)}
                />
              ))}
              {!recents.length && <div className="sb-empty">Your chats will show up here.</div>}
            </div>
          </div>
        </nav>

        <div className="sb-foot">
          <button
            type="button"
            className={`sb-profile${tab === "settings" ? " active" : ""}`}
            title="Settings"
            onClick={() => selectTab("settings")}
          >
            <span className="avatar">{(appearance.name.trim()[0] ?? "S").toUpperCase()}</span>
            <span className="sb-profile-text">
              <strong>{appearance.name.trim() || "Settings"}</strong>
              <small>
                <span className={`dot ${online ? "ok" : "off"}`} />
                {online ? modelLabel ?? "Backend online" : "Backend offline"}
                {online && health && !health.vault_exists ? " · vault missing" : ""}
              </small>
            </span>
          </button>
        </div>
      </aside>

      <div className="main-col">
        <header className="main-header">
          <button
            type="button"
            className="icon-btn mobile-menu"
            aria-label="Open sidebar"
            onClick={() => setMobileNav(true)}
          >
            <Icon name="menu" size={18} />
          </button>

          {tab === "notes" && (
            <button
              type="button"
              className={`icon-btn ${treeOpen ? "active" : ""}`}
              title="Toggle file tree"
              onClick={() => setTreeOpen((o) => !o)}
            >
              <Icon name="folder" size={17} />
            </button>
          )}

          {tab === "chat" ? (
            activeChat ? (
              titleEdit !== null ? (
                <input
                  className="header-title-input"
                  autoFocus
                  value={titleEdit}
                  onChange={(e) => setTitleEdit(e.target.value)}
                  onBlur={() => {
                    if (titleEdit.trim() !== activeChat.title) void renameChat(activeChat.id, titleEdit);
                    setTitleEdit(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.nativeEvent.isComposing) return;
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    if (e.key === "Escape") setTitleEdit(null);
                  }}
                />
              ) : (
                <div className="menu-wrap" ref={titleWrap}>
                  <button type="button" className="header-title-btn" onClick={() => setTitleMenu((m) => !m)}>
                    <span>{activeChat.title}</span>
                    <Icon name="chevron-down" size={14} />
                  </button>
                  {titleMenu && (
                    <div className="popover" style={{ left: 0, top: "calc(100% + 4px)", minWidth: 190 }}>
                      <button
                        type="button"
                        className="popover-item"
                        onClick={() => {
                          setTitleMenu(false);
                          setTitleEdit(activeChat.title);
                        }}
                      >
                        <Icon name="pencil" size={15} /> Rename
                      </button>
                      <button
                        type="button"
                        className="popover-item danger"
                        onClick={() => {
                          setTitleMenu(false);
                          void deleteChat(activeChat.id);
                        }}
                      >
                        <Icon name="trash" size={15} /> Delete
                      </button>
                    </div>
                  )}
                </div>
              )
            ) : null
          ) : (
            <div className="crumb">
              {tab === "notes" &&
                (noteCrumbs.length ? (
                  noteCrumbs.map((part, index) => (
                    <span key={index} className={index < noteCrumbs.length - 1 ? "crumb-dim" : ""}>
                      {index > 0 && <span className="crumb-dim"> / </span>}
                      {part}
                    </span>
                  ))
                ) : (
                  <span>{current?.label}</span>
                ))}
            </div>
          )}

          <div className="grow" />

          {tab === "notes" && (
            <button
              type="button"
              className={`icon-btn ${tocOpen ? "active" : ""}`}
              title="Toggle outline"
              onClick={() => setTocOpen((o) => !o)}
            >
              <Icon name="panel-right" size={17} />
            </button>
          )}
          {tab !== "chat" && (
            <button
              type="button"
              className={`icon-btn ${dockOpen ? "active" : ""}`}
              title="Chat with your notes"
              aria-label="Toggle chat panel"
              onClick={() => {
                // Give the notes column room: the outline hides while chat is open on smaller screens.
                if (!dockOpen && tab === "notes" && window.innerWidth < 1600) setTocOpen(false);
                setDockOpen((o) => !o);
              }}
            >
              <Icon name="message-circle" size={17} />
            </button>
          )}
        </header>

        <div className="main-row">
          <main className={`main${tab === "chat" ? " flush" : ""}${tab === "notes" ? " notes-main" : ""}`}>
            <div className="chat-keepalive" hidden={tab !== "chat"}>
              <ChatPage
                key={`main-${chatKey}`}
                conversationId={chatConvId}
                initialInput={chatDraft}
                userName={appearance.name}
                modelLabel={modelLabel}
                vaultRoot={vaultRoot}
                onConversationCreated={(id) => setChatConvId(id)}
                onActivity={refreshRecents}
                onOpenNote={openNote}
                onNavigate={(next) => selectTab(next as Tab)}
                onQuiz={quizFromAnswer}
                showToday
              />
            </div>
            {notesMounted && (
              <div className="notes-keepalive" hidden={tab !== "notes"}>
                <Suspense fallback={<PageLoading />}>
                  <NotesPage
                    key={vaultRevision}
                    path={notePath}
                    openSeq={noteOpenSeq}
                    tocOpen={tocOpen}
                    treeOpen={treeOpen}
                    onActiveChange={setActiveNotePath}
                  />
                </Suspense>
              </div>
            )}
            <Suspense fallback={<PageLoading />}>
              {tab === "today" && (
                <TodayPage
                  onQuiz={(request) =>
                    startQuiz({
                      ...request,
                      origin: `Quiz on “${request.topic}”${request.course ? ` · ${request.course}` : ""}.`,
                    })
                  }
                  onAsk={(prompt) => newChat(prompt)}
                  onNavigate={(next) => selectTab(next as Tab)}
                />
              )}
              {tab === "lectures" && <LecturesPage />}
              {tab === "voice" && <VoiceNotesPage onOpenNote={openNote} />}
              {tab === "wiki" && <WikiPage onOpenNote={openNote} />}
              {FRAMED.includes(tab) && (
                <div className="page-frame">
                  {tab === "search" && <SearchPage />}
                  {tab === "generate" && <GeneratePage />}
                  {tab === "quiz" && <QuizPage preset={quizPreset} />}
                  {tab === "progress" && <ProgressPage />}
                  {tab === "plan" && <PlanPage />}
                  {tab === "papers" && <PastPapersPage />}
                  {tab === "library" && <LibraryPage />}
                  {tab === "settings" && (
                    <SettingsPage
                      onAppearanceChange={setAppearance}
                      onSaved={() => {
                        setVaultRevision((value) => value + 1);
                        api
                          .health()
                          .then((h) => (setHealth(h), setOnline(true)))
                          .catch(() => setOnline(false));
                        refreshSettings();
                      }}
                    />
                  )}
                </div>
              )}
            </Suspense>
          </main>

          {tab !== "chat" && (
            <aside className={`chat-dock${dockOpen ? " open" : ""}`} aria-hidden={!dockOpen}>
              {dockMounted && (
                <div className="dock-inner" hidden={!dockOpen}>
                  <div className="dock-head">
                    <strong>Chat</strong>
                    <div className="grow" />
                    <button
                      type="button"
                      className="icon-btn"
                      title="New chat"
                      onClick={() => {
                        setDockConvId(null);
                        setDockKey((k) => k + 1);
                      }}
                    >
                      <Icon name="square-pen" size={16} />
                    </button>
                    {dockConvId && (
                      <button
                        type="button"
                        className="icon-btn"
                        title="Open in full view"
                        onClick={() => {
                          setDockOpen(false);
                          openChat(dockConvId);
                        }}
                      >
                        <Icon name="maximize" size={15} />
                      </button>
                    )}
                    <button type="button" className="icon-btn" title="Close" onClick={() => setDockOpen(false)}>
                      <Icon name="x" size={16} />
                    </button>
                  </div>
                  <div className="dock-body">
                    <ChatPage
                      key={`dock-${dockKey}`}
                      compact
                      conversationId={dockConvId}
                      modelLabel={modelLabel}
                      vaultRoot={vaultRoot}
                      activeNote={dockNote}
                      onConversationCreated={(id) => setDockConvId(id)}
                      onActivity={refreshRecents}
                      onOpenNote={openNote}
                      onQuiz={quizFromAnswer}
                    />
                  </div>
                </div>
              )}
            </aside>
          )}
        </div>
      </div>

      {quickOpen && (
        <QuickOpen
          recents={recents}
          onClose={() => setQuickOpen(false)}
          onOpenNote={openNote}
          onOpenChat={openChat}
          onOpenTab={(next) => (next === "chat" ? newChat() : selectTab(next))}
        />
      )}
    </div>
  );
}
