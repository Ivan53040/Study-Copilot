import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { api } from "../api";
import { Icon } from "../icons";
import type { TreeNode, VaultNote } from "../types";

const slug = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
const stripExt = (name: string) => name.replace(/\.(md|markdown|txt)$/i, "");
const basename = (p: string) => p.split("/").pop() ?? p;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function stripFrontmatter(raw: string): string {
  if (raw.startsWith("---")) {
    const end = raw.indexOf("\n---", 3);
    if (end !== -1) {
      const nl = raw.indexOf("\n", end + 1);
      return nl !== -1 ? raw.slice(nl + 1) : "";
    }
  }
  return raw;
}

function wikilinksToMd(text: string): string {
  return text.replace(
    /\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g,
    (_m, name: string, alias?: string) =>
      `[${(alias || name).trim()}](wikilink:${encodeURIComponent(name.trim())})`,
  );
}

function toText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(toText).join("");
  if (children && typeof children === "object" && "props" in (children as any))
    return toText((children as any).props.children);
  return "";
}

function collectFolders(node: TreeNode, acc: string[] = []): string[] {
  node.children?.forEach((c) => {
    if (c.type === "folder") {
      acc.push(c.path);
      collectFolders(c, acc);
    }
  });
  return acc;
}

function ancestorsOf(path: string): string[] {
  const parts = path.split("/");
  const out: string[] = [];
  for (let i = 1; i < parts.length; i++) out.push(parts.slice(0, i).join("/"));
  return out;
}

function sortChildren(children: TreeNode[], dir: "asc" | "desc"): TreeNode[] {
  const folders = children.filter((c) => c.type === "folder");
  const files = children.filter((c) => c.type === "file");
  const cmp = (a: TreeNode, b: TreeNode) =>
    dir === "asc" ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
  folders.sort(cmp);
  files.sort(cmp);
  return [...folders, ...files];
}

interface NodeProps {
  node: TreeNode;
  depth: number;
  current: string | null;
  expanded: Set<string>;
  sortDir: "asc" | "desc";
  onToggle: (p: string) => void;
  onOpen: (p: string, newTab: boolean) => void;
  activeRef: React.RefObject<HTMLDivElement>;
}

function TreeNodeView(props: NodeProps) {
  const { node, depth, current, expanded, sortDir, onToggle, onOpen, activeRef } =
    props;

  if (node.type === "file") {
    const active = current === node.path;
    return (
      <div
        ref={active ? activeRef : undefined}
        className={`tree-row ${active ? "active" : ""}`}
        style={{ paddingLeft: 6 + depth * 12 }}
        onClick={(e) => onOpen(node.path, e.ctrlKey || e.metaKey)}
        title={node.path}
      >
        {stripExt(node.name)}
      </div>
    );
  }

  const isRoot = node.name === "";
  const open = isRoot || expanded.has(node.path);
  return (
    <div>
      {!isRoot && (
        <div
          className="tree-row tree-folder"
          style={{ paddingLeft: 6 + depth * 12 }}
          onClick={() => onToggle(node.path)}
        >
          {open ? "▾" : "▸"} {node.name}
        </div>
      )}
      {open &&
        sortChildren(node.children ?? [], sortDir).map((c) => (
          <TreeNodeView
            key={c.path}
            {...props}
            node={c}
            depth={isRoot ? depth : depth + 1}
          />
        ))}
    </div>
  );
}

// Empty-tab note picker: search the vault and open a note into this tab.
function NewTabPicker({ onPick }: { onPick: (path: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ path: string; title: string }[]>([]);
  useEffect(() => {
    let alive = true;
    api
      .vaultSearch(q)
      .then((r) => alive && setResults(r.results.slice(0, 20)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [q]);
  return (
    <div className="newtab-picker">
      <input
        autoFocus
        placeholder="Search notes to open…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="newtab-results">
        {results.map((r) => (
          <div
            key={r.path}
            className="newtab-result"
            onClick={() => onPick(r.path)}
          >
            {r.title} <span className="muted small">· {r.path}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function NotesPage({
  path,
  tocOpen,
  treeOpen,
}: {
  path: string | null;
  tocOpen: boolean;
  treeOpen: boolean;
}) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [tabs, setTabs] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [note, setNote] = useState<VaultNote | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [treeWidth, setTreeWidth] = useState(
    () => Number(localStorage.getItem("ws.treeWidth")) || 240,
  );
  const [tocWidth, setTocWidth] = useState(
    () => Number(localStorage.getItem("ws.tocWidth")) || 240,
  );
  const activeRef = useRef<string | null>(null);
  const activeRowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);
  useEffect(() => localStorage.setItem("ws.treeWidth", String(treeWidth)), [treeWidth]);
  useEffect(() => localStorage.setItem("ws.tocWidth", String(tocWidth)), [tocWidth]);

  const refreshTree = () => api.vaultTree().then(setTree);

  const newCounter = useRef(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const flash = (m: string) => {
    setBanner(m);
    setTimeout(() => setBanner(null), 4000);
  };
  const isNewTab = (id: string | null) => !!id && id.startsWith("new:");

  const openNewTab = () => {
    const id = `new:${++newCounter.current}`;
    setTabs((p) => [...p, id]);
    setActive(id);
  };
  const pickInNewTab = (path: string) => {
    setTabs((prev) => {
      const arr = prev.filter((x) => x !== activeRef.current);
      if (!arr.includes(path)) arr.push(path);
      return arr;
    });
    setActive(path);
  };

  const openInTab = useCallback((p: string, newTab: boolean) => {
    setTabs((prev) => {
      if (prev.includes(p)) return prev;
      if (newTab || !activeRef.current) return [...prev, p];
      return prev.map((x) => (x === activeRef.current ? p : x));
    });
    setActive(p);
  }, []);

  const closeTab = useCallback((p: string) => {
    setTabs((prev) => {
      const idx = prev.indexOf(p);
      const next = prev.filter((x) => x !== p);
      if (activeRef.current === p) {
        const fallback = next[idx] ?? next[idx - 1] ?? next[next.length - 1] ?? null;
        setActive(fallback);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    api
      .vaultTree()
      .then((t) => {
        setTree(t);
        setExpanded(
          new Set(
            (t.children ?? []).filter((c) => c.type === "folder").map((c) => c.path),
          ),
        );
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  // External open request (graph / quick-open) -> open in a tab.
  useEffect(() => {
    if (path) openInTab(path, true);
  }, [path, openInTab]);

  // Load the active note (skip empty "new tab" placeholders).
  useEffect(() => {
    if (!active || active.startsWith("new:")) {
      setNote(null);
      return;
    }
    setEditing(false);
    setError(null);
    setExpanded((prev) => new Set([...prev, ...ancestorsOf(active)]));
    api
      .vaultNote(active)
      .then((n) => {
        setNote(n);
        setDraft(n.content);
      })
      .catch((e) => setError((e as Error).message));
  }, [active]);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [note]);

  const linkMap = useMemo(() => {
    const m: Record<string, string | null> = {};
    note?.links.forEach((l) => (m[l.name.toLowerCase()] = l.path));
    return m;
  }, [note]);

  const components: Components = useMemo(() => {
    const heading = (Tag: "h1" | "h2" | "h3" | "h4" | "h5" | "h6") =>
      ({ children }: any) => <Tag id={slug(toText(children))}>{children}</Tag>;
    return {
      a: ({ href, children }: any) => {
        if (href?.startsWith("wikilink:")) {
          const name = decodeURIComponent(href.slice("wikilink:".length));
          const target = linkMap[name.toLowerCase()];
          return (
            <span
              className={`wikilink ${target ? "" : "missing"}`}
              onClick={(e) => target && openInTab(target, e.ctrlKey || e.metaKey)}
            >
              {children}
            </span>
          );
        }
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        );
      },
      h1: heading("h1"),
      h2: heading("h2"),
      h3: heading("h3"),
      h4: heading("h4"),
      h5: heading("h5"),
      h6: heading("h6"),
    };
  }, [linkMap, openInTab]);

  const rendered = useMemo(
    () => (note ? wikilinksToMd(stripFrontmatter(note.content)) : ""),
    [note],
  );

  const toggleFolder = (p: string) =>
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(p) ? n.delete(p) : n.add(p);
      return n;
    });

  const newNote = async () => {
    const name = window.prompt("New note (optionally Folder/Name):");
    if (!name) return;
    let p = name.trim();
    if (!/\.(md|markdown|txt)$/i.test(p)) p += ".md";
    try {
      await api.vaultSaveNote(p, `# ${stripExt(basename(p))}\n\n`);
      await refreshTree();
      setExpanded((prev) => new Set([...prev, ...ancestorsOf(p)]));
      openInTab(p, true);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const newFolder = async () => {
    const name = window.prompt("New folder (optionally Parent/Child):");
    if (!name) return;
    try {
      await api.vaultCreateFolder(name.trim());
      await refreshTree();
      setExpanded((prev) => new Set([...prev, name.trim(), ...ancestorsOf(name.trim())]));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const reveal = () => {
    if (active) {
      setExpanded((prev) => new Set([...prev, ...ancestorsOf(active)]));
      setTimeout(() => activeRowRef.current?.scrollIntoView({ block: "center" }), 50);
    }
  };

  const allFolders = tree ? collectFolders(tree) : [];
  const allExpanded = expanded.size >= allFolders.length && allFolders.length > 0;
  const toggleExpandAll = () =>
    setExpanded(allExpanded ? new Set() : new Set(allFolders));

  const startResize = (e: React.MouseEvent, side: "tree" | "toc") => {
    e.preventDefault();
    const startX = e.clientX;
    const startTree = treeWidth;
    const startToc = tocWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      if (side === "tree") setTreeWidth(clamp(startTree + dx, 160, 520));
      else setTocWidth(clamp(startToc - dx, 150, 480));
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const save = async () => {
    if (!note) return;
    setSaving(true);
    setError(null);
    try {
      await api.vaultSaveNote(note.path, draft);
      const fresh = await api.vaultNote(note.path);
      setNote(fresh);
      setDraft(fresh.content);
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const toggleEdit = async () => {
    if (!note) return;
    if (editing) {
      if (draft !== note.content) await save();
      setEditing(false);
    } else {
      setEditing(true);
    }
  };

  // --- tab-bar more-options actions (operate on the active note) ---
  const actionable = !!note && !isNewTab(active);

  const handleRename = async () => {
    if (!actionable || !active) return;
    const cur = basename(active);
    const name = window.prompt("Rename note to:", cur);
    if (!name || name === cur) return;
    const dir = active.includes("/") ? active.slice(0, active.lastIndexOf("/") + 1) : "";
    let to = dir + name;
    if (!/\.(md|markdown|txt)$/i.test(to)) to += ".md";
    try {
      const r = await api.vaultRename(active, to);
      setTabs((p) => p.map((x) => (x === active ? r.to : x)));
      setActive(r.to);
      await refreshTree();
    } catch (e) {
      flash((e as Error).message);
    }
  };

  const handleMove = async () => {
    if (!actionable || !active) return;
    const curDir = active.includes("/") ? active.slice(0, active.lastIndexOf("/")) : "";
    const folder = window.prompt("Move to folder (vault-relative):", curDir);
    if (folder === null) return;
    const to = (folder ? folder.replace(/\/+$/, "") + "/" : "") + basename(active);
    try {
      const r = await api.vaultRename(active, to);
      setTabs((p) => p.map((x) => (x === active ? r.to : x)));
      setActive(r.to);
      await refreshTree();
    } catch (e) {
      flash((e as Error).message);
    }
  };

  const handleCopyPath = async () => {
    if (!actionable || !active) return;
    try {
      await navigator.clipboard.writeText(active);
      flash("Path copied");
    } catch {
      flash(active);
    }
  };

  const handleReveal = async () => {
    if (actionable && active) {
      try { await api.vaultReveal(active); } catch (e) { flash((e as Error).message); }
    }
  };
  const handleOpenExternal = async () => {
    if (actionable && active) {
      try { await api.vaultOpenExternal(active); } catch (e) { flash((e as Error).message); }
    }
  };
  const handleExportPdf = async () => {
    if (!actionable || !active) return;
    try {
      const r = await api.vaultExportPdf(active);
      flash(`Exported PDF: ${r.pdf}`);
      const rel = `StudyCopilot/Exports/${stripExt(basename(active))}.pdf`;
      api.vaultOpenExternal(rel).catch(() => {});
    } catch (e) {
      flash((e as Error).message);
    }
  };
  const handleDelete = async () => {
    if (!actionable || !active) return;
    if (!window.confirm(`Delete "${basename(active)}"?\nIt is moved to a backup (reversible).`)) return;
    const target = active;
    try {
      await api.vaultDelete(target);
      closeTab(target);
      await refreshTree();
      flash("Deleted (backup kept)");
    } catch (e) {
      flash((e as Error).message);
    }
  };

  const showToc = tocOpen && !!note;

  return (
    <div className="workspace">
      <div className="ws-tree" style={{ width: treeOpen ? treeWidth : 0 }}>
        <div className="ws-tree-inner" style={{ width: treeWidth }}>
          <div className="tree-toolbar">
            <button className="icon-btn" title="New note" onClick={newNote}>
              <Icon name="file-plus" />
            </button>
            <button className="icon-btn" title="New folder" onClick={newFolder}>
              <Icon name="folder-plus" />
            </button>
            <button
              className="icon-btn"
              title={`Sort ${sortDir === "asc" ? "Z→A" : "A→Z"}`}
              onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
            >
              <Icon name="sort" />
            </button>
            <button className="icon-btn" title="Reveal current note" onClick={reveal}>
              <Icon name="reveal" />
            </button>
            <button
              className="icon-btn"
              title={allExpanded ? "Collapse all" : "Expand all"}
              onClick={toggleExpandAll}
            >
              <Icon name={allExpanded ? "collapse" : "expand"} />
            </button>
          </div>
          {tree ? (
            <TreeNodeView
              node={tree}
              depth={0}
              current={active}
              expanded={expanded}
              sortDir={sortDir}
              onToggle={toggleFolder}
              onOpen={openInTab}
              activeRef={activeRowRef}
            />
          ) : (
            <div className="muted small">Loading…</div>
          )}
        </div>
      </div>
      {treeOpen && (
        <div className="resizer" onMouseDown={(e) => startResize(e, "tree")} />
      )}

      <div className="ws-main">
        <div className="tabbar">
          {tabs.map((p) => (
            <div
              key={p}
              className={`tab ${p === active ? "active" : ""} ${isNewTab(p) ? "newtab" : ""}`}
              onClick={() => setActive(p)}
              onMouseDown={(e) => {
                if (e.button === 1) {
                  e.preventDefault();
                  closeTab(p);
                }
              }}
              title={isNewTab(p) ? "New tab" : p}
            >
              <span className="tab-label">
                {isNewTab(p) ? "New tab" : stripExt(basename(p))}
              </span>
              <span
                className="tab-close"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(p);
                }}
              >
                ✕
              </span>
            </div>
          ))}
          <button className="tab-add icon-btn" title="Open new tab" onClick={openNewTab}>
            +
          </button>

          {actionable && (
            <div className="tab-actions">
              {editing && note && draft !== note.content && (
                <button
                  className="icon-btn"
                  style={{ color: "var(--accent)" }}
                  title="Save"
                  onClick={save}
                  disabled={saving}
                >
                  Save
                </button>
              )}
              <button
                className="icon-btn"
                title={editing ? "Reading view" : "Edit"}
                onClick={toggleEdit}
              >
                <Icon name={editing ? "pencil" : "book"} size={17} />
              </button>
              <div className="menu-wrap">
                <button
                  className="icon-btn"
                  title="More options"
                  onClick={() => setMenuOpen((o) => !o)}
                >
                  <Icon name="more-vertical" size={17} />
                </button>
                {menuOpen && (
                  <>
                    <div className="menu-backdrop" onClick={() => setMenuOpen(false)} />
                    <div className="more-menu">
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleRename(); }}>
                        <Icon name="pencil" size={15} /> Rename…
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleMove(); }}>
                        <Icon name="folder" size={15} /> Move to folder…
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleCopyPath(); }}>
                        <Icon name="copy" size={15} /> Copy path
                      </button>
                      <div className="more-sep" />
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleReveal(); }}>
                        <Icon name="reveal" size={15} /> Reveal in file explorer
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleOpenExternal(); }}>
                        <Icon name="external-link" size={15} /> Open in default app
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleExportPdf(); }}>
                        <Icon name="download" size={15} /> Export to PDF
                      </button>
                      <div className="more-sep" />
                      <button className="more-item danger" onClick={() => { setMenuOpen(false); handleDelete(); }}>
                        <Icon name="trash" size={15} /> Delete file
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="ws-content">
          {banner && <div className="note-banner">{banner}</div>}
          {error && <div className="warn-banner">{error}</div>}
          {isNewTab(active) ? (
            <NewTabPicker onPick={pickInNewTab} />
          ) : !note ? (
            <div className="muted">Select a note from the tree, or press + for a new tab.</div>
          ) : (
            <>
              <h2 className="page-title" style={{ margin: "0 0 4px" }}>{note.name}</h2>
              <div className="small muted" style={{ marginBottom: 12 }}>{note.path}</div>
              {editing ? (
                <textarea
                  className="editor"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
              ) : (
                <div className="md">
                  <ReactMarkdown components={components}>{rendered}</ReactMarkdown>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {showToc && (
        <div className="resizer" onMouseDown={(e) => startResize(e, "toc")} />
      )}
      <div className="ws-toc" style={{ width: showToc ? tocWidth : 0 }}>
        <div className="ws-toc-inner" style={{ width: tocWidth }}>
          {note && note.headings.length > 0 && (
            <>
              <div className="small muted" style={{ marginBottom: 6 }}>On this page</div>
              {note.headings.map((h, i) => (
                <a
                  key={i}
                  className="toc-item"
                  href={`#${h.slug}`}
                  style={{ paddingLeft: (h.level - 1) * 10 }}
                >
                  {h.text}
                </a>
              ))}
            </>
          )}
          {note && note.backlinks.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="small muted" style={{ marginBottom: 6 }}>
                Linked mentions ({note.backlinks.length})
              </div>
              {note.backlinks.map((b) => (
                <div
                  key={b.path}
                  className="toc-item"
                  onClick={(e) => openInTab(b.path, e.ctrlKey || e.metaKey)}
                >
                  {b.title}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
