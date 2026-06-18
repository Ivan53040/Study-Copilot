import { useEffect, useMemo, useState } from "react";
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

// [[Target]], [[Target#h]], [[Target|alias]] -> [alias|Target](wikilink:Target)
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

interface TreeProps {
  node: TreeNode;
  depth: number;
  current: string | null;
  onOpen: (path: string) => void;
}

function Tree({ node, depth, current, onOpen }: TreeProps) {
  const [open, setOpen] = useState(depth < 1);
  if (node.type === "file") {
    return (
      <div
        className={`tree-row ${current === node.path ? "active" : ""}`}
        style={{ paddingLeft: 6 + depth * 12 }}
        onClick={() => onOpen(node.path)}
        title={node.path}
      >
        {node.name.replace(/\.(md|markdown|txt)$/, "")}
      </div>
    );
  }
  return (
    <div>
      {node.name && (
        <div
          className="tree-row tree-folder"
          style={{ paddingLeft: 6 + depth * 12 }}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "▾" : "▸"} {node.name}
        </div>
      )}
      {open &&
        node.children?.map((c) => (
          <Tree
            key={c.path}
            node={c}
            depth={node.name ? depth + 1 : depth}
            current={current}
            onOpen={onOpen}
          />
        ))}
    </div>
  );
}

export function NotesPage({
  path,
  onOpen,
}: {
  path: string | null;
  onOpen: (path: string) => void;
}) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [note, setNote] = useState<VaultNote | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.vaultTree().then(setTree).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (!path) return;
    setEditing(false);
    setError(null);
    api
      .vaultNote(path)
      .then((n) => {
        setNote(n);
        setDraft(n.content);
      })
      .catch((e) => setError((e as Error).message));
  }, [path]);

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
        {tree ? (
          <Tree node={tree} depth={0} current={note?.path ?? null} onOpen={onOpen} />
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

      <div className="ws-toc">
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
              <div key={b.path} className="toc-item" onClick={() => onOpen(b.path)}>
                {b.title}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
