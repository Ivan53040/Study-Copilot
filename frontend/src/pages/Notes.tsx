import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { api } from "../api";
import type { TreeNode, VaultNote } from "../types";

const slug = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

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

const stripExt = (name: string) => name.replace(/\.(md|markdown|txt)$/i, "");

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
  onOpen: (p: string) => void;
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
        onClick={() => onOpen(node.path)}
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

export function NotesPage({
  path,
  onOpen,
  tocOpen,
}: {
  path: string | null;
  onOpen: (path: string) => void;
  tocOpen: boolean;
}) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [note, setNote] = useState<VaultNote | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const activeRef = useRef<HTMLDivElement>(null);

  const refreshTree = () => api.vaultTree().then(setTree);

  useEffect(() => {
    api
      .vaultTree()
      .then((t) => {
        setTree(t);
        // Expand top-level folders by default.
        setExpanded(
          new Set((t.children ?? []).filter((c) => c.type === "folder").map((c) => c.path)),
        );
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (!path) return;
    setEditing(false);
    setError(null);
    setExpanded((prev) => new Set([...prev, ...ancestorsOf(path)]));
    api
      .vaultNote(path)
      .then((n) => {
        setNote(n);
        setDraft(n.content);
      })
      .catch((e) => setError((e as Error).message));
  }, [path]);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
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
              onClick={() => target && onOpen(target)}
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
  }, [linkMap, onOpen]);

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
      await api.vaultSaveNote(p, `# ${stripExt(p.split("/").pop()!)}\n\n`);
      await refreshTree();
      setExpanded((prev) => new Set([...prev, ...ancestorsOf(p)]));
      onOpen(p);
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
    if (note) {
      setExpanded((prev) => new Set([...prev, ...ancestorsOf(note.path)]));
      setTimeout(
        () => activeRef.current?.scrollIntoView({ block: "center" }),
        50,
      );
    }
  };

  const allFolders = tree ? collectFolders(tree) : [];
  const allExpanded = expanded.size >= allFolders.length && allFolders.length > 0;
  const toggleExpandAll = () =>
    setExpanded(allExpanded ? new Set() : new Set(allFolders));

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

  return (
    <div className="workspace">
      <div className="ws-tree">
        <div className="tree-toolbar">
          <button className="icon-btn" title="New note" onClick={newNote}>🗎﹢</button>
          <button className="icon-btn" title="New folder" onClick={newFolder}>🗀﹢</button>
          <button
            className="icon-btn"
            title={`Sort ${sortDir === "asc" ? "Z→A" : "A→Z"}`}
            onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
          >
            {sortDir === "asc" ? "↓A" : "↑Z"}
          </button>
          <button className="icon-btn" title="Reveal current note" onClick={reveal}>
            ⊙
          </button>
          <button
            className="icon-btn"
            title={allExpanded ? "Collapse all" : "Expand all"}
            onClick={toggleExpandAll}
          >
            {allExpanded ? "⤡" : "⤢"}
          </button>
        </div>
        {tree ? (
          <TreeNodeView
            node={tree}
            depth={0}
            current={note?.path ?? null}
            expanded={expanded}
            sortDir={sortDir}
            onToggle={toggleFolder}
            onOpen={onOpen}
            activeRef={activeRef}
          />
        ) : (
          <div className="muted small">Loading…</div>
        )}
      </div>

      <div className="ws-main">
        {error && <div className="warn-banner">{error}</div>}
        {!note ? (
          <div className="muted">Select a note from the tree.</div>
        ) : (
          <>
            <div className="row" style={{ marginBottom: 10, alignItems: "center" }}>
              <h2 className="page-title" style={{ margin: 0 }}>{note.name}</h2>
              <div className="grow" />
              {note.editable &&
                (editing ? (
                  <>
                    <button className="primary" onClick={save} disabled={saving}>
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button onClick={() => { setEditing(false); setDraft(note.content); }}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button onClick={() => setEditing(true)}>Edit</button>
                ))}
            </div>
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

      {tocOpen && note && (note.headings.length > 0 || note.backlinks.length > 0) && (
        <div className="ws-toc">
          {note.headings.length > 0 && (
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
          {note.backlinks.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="small muted" style={{ marginBottom: 6 }}>
                Linked mentions ({note.backlinks.length})
              </div>
              {note.backlinks.map((b) => (
                <div key={b.path} className="toc-item" onClick={() => onOpen(b.path)}>
                  {b.title}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
