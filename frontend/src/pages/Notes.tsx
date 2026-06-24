import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { api } from "../api";
import { Icon } from "../icons";
import { MarkdownEditor } from "../MarkdownEditor";
import { RichMarkdownEditor } from "../RichMarkdownEditor";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";
import type {
  FormatPreview,
  NoteVersion,
  OrganizerPreview,
  TreeNode,
  VaultNote,
} from "../types";

const slug = (s: string) =>
  s
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/^-+|-+$/g, "");
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
  onContext: (event: React.MouseEvent, path: string, type: "file" | "folder") => void;
  onDragGesture: (
    source: string,
    type: "file" | "folder",
    event: React.MouseEvent,
  ) => void;
  dragTarget: string | null;
  activeRef: React.RefObject<HTMLDivElement>;
}

function TreeNodeView(props: NodeProps) {
  const {
    node, depth, current, expanded, sortDir, onToggle, onOpen, onContext,
    onDragGesture, dragTarget, activeRef,
  } =
    props;

  if (node.type === "file") {
    const active = current === node.path;
    return (
      <div
        ref={active ? activeRef : undefined}
        className={`tree-row ${active ? "active" : ""}`}
        style={{ paddingLeft: 6 + depth * 12 }}
        onClick={(e) => onOpen(node.path, e.ctrlKey || e.metaKey)}
        onContextMenu={(e) => onContext(e, node.path, "file")}
        onMouseDown={(event) => onDragGesture(node.path, "file", event)}
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
          className={`tree-row tree-folder ${dragTarget === node.path ? "drag-target" : ""}`}
          style={{ paddingLeft: 6 + depth * 12 }}
          onClick={() => onToggle(node.path)}
          onContextMenu={(e) => onContext(e, node.path, "folder")}
          data-folder-path={node.path}
          onMouseDown={(event) => onDragGesture(node.path, "folder", event)}
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
  detached = false,
}: {
  path: string | null;
  tocOpen: boolean;
  treeOpen: boolean;
  detached?: boolean;
}) {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [tabs, setTabs] = useState<string[]>(() => {
    if (detached && path) return [path];
    try { return JSON.parse(localStorage.getItem("ws.tabs") ?? "[]"); }
    catch { return []; }
  });
  const [active, setActive] = useState<string | null>(
    () => detached && path ? path : localStorage.getItem("ws.active"),
  );
  const [note, setNote] = useState<VaultNote | null>(null);
  const [viewMode, setViewMode] = useState<"source" | "edit" | "read">("read");
  const editing = viewMode !== "read";
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem("ws.expanded") ?? "[]"));
    } catch {
      return new Set();
    }
  });
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
  const [align, setAlign] = useState<"left" | "center">(
    () => (localStorage.getItem("ws.align") as "left" | "center") || "left",
  );
  const [readingZoom, setReadingZoom] = useState(
    () => Number(localStorage.getItem("ws.readingZoom")) || 100,
  );
  const [textSizeMenu, setTextSizeMenu] = useState(false);
  const [textSizePosition, setTextSizePosition] = useState({ top: 0, left: 0 });
  useEffect(() => localStorage.setItem("ws.treeWidth", String(treeWidth)), [treeWidth]);
  useEffect(() => localStorage.setItem("ws.tocWidth", String(tocWidth)), [tocWidth]);
  useEffect(() => localStorage.setItem("ws.align", align), [align]);
  useEffect(() => localStorage.setItem("ws.readingZoom", String(readingZoom)), [readingZoom]);
  useEffect(() => {
    if (!detached) localStorage.setItem("ws.tabs", JSON.stringify(tabs));
  }, [detached, tabs]);
  useEffect(() => {
    if (detached) return;
    if (active) localStorage.setItem("ws.active", active);
    else localStorage.removeItem("ws.active");
  }, [active, detached]);
  useEffect(
    () => localStorage.setItem("ws.expanded", JSON.stringify([...expanded])),
    [expanded],
  );

  const refreshTree = () => api.vaultTree().then(setTree);

  const newCounter = useRef(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [banner, setBanner] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    path: string;
    type: "file" | "folder";
    x: number;
    y: number;
  } | null>(null);
  const [organizer, setOrganizer] = useState<OrganizerPreview | null>(null);
  const [selectedOrganizerMoves, setSelectedOrganizerMoves] = useState<Set<string>>(
    new Set(),
  );
  const [organizing, setOrganizing] = useState(false);
  const [formatPreview, setFormatPreview] = useState<FormatPreview | null>(null);
  const [formatting, setFormatting] = useState(false);
  const [split, setSplit] = useState<"right" | "down" | null>(null);
  const [splitPath, setSplitPath] = useState<string | null>(null);
  const [splitNote, setSplitNote] = useState<VaultNote | null>(null);
  const [backlinksInDocument, setBacklinksInDocument] = useState(
    () => localStorage.getItem("ws.backlinksInDocument") === "true",
  );
  const [bookmarks, setBookmarks] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem("ws.bookmarks") ?? "[]")); }
    catch { return new Set(); }
  });
  const [bookmarkMenu, setBookmarkMenu] = useState(false);
  const [linkedMenu, setLinkedMenu] = useState(false);
  const [findMode, setFindMode] = useState<"find" | "replace" | null>(null);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [replaceUndo, setReplaceUndo] = useState<
    { path: string; before: string; after: string }[]
  >([]);
  const [replaceRedo, setReplaceRedo] = useState<
    { path: string; before: string; after: string }[]
  >([]);
  const [pendingHeading, setPendingHeading] = useState<string | null>(null);
  const [versions, setVersions] = useState<NoteVersion[] | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [internalDrag, setInternalDrag] = useState<{
    path: string;
    type: "file" | "folder";
    x: number;
    y: number;
    target: string | null;
    overNote: boolean;
  } | null>(null);
  useEffect(
    () => localStorage.setItem("ws.bookmarks", JSON.stringify([...bookmarks])),
    [bookmarks],
  );
  useEffect(
    () => localStorage.setItem("ws.backlinksInDocument", String(backlinksInDocument)),
    [backlinksInDocument],
  );
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
    setViewMode("read");
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
    if (!splitPath) {
      setSplitNote(null);
      return;
    }
    api.vaultNote(splitPath).then(setSplitNote).catch(() => setSplitNote(null));
  }, [splitPath]);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [note]);

  useEffect(() => {
    if (!note || !pendingHeading || editing) return;
    const timer = window.setTimeout(() => {
      document.getElementById(pendingHeading)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
      setPendingHeading(null);
    }, 80);
    return () => window.clearTimeout(timer);
  }, [editing, note, pendingHeading]);

  const linkMap = useMemo(() => {
    const m: Record<string, string | null> = {};
    note?.links.forEach((l) => (m[l.name.toLowerCase()] = l.path));
    return m;
  }, [note]);

  const openExternalUrl = useCallback(async (url: string) => {
    if ("__TAURI_INTERNALS__" in window) {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
    } else {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }, []);

  const openLinkedNote = useCallback(
    async (rawTarget: string, newTab = true) => {
      if (!rawTarget) return;
      const decoded = decodeURIComponent(rawTarget)
        .replace(/^wikilink:/i, "")
        .replace(/^https?:\/\/tauri\.localhost\/?/i, "")
        .replace(/^\.\//, "");
      const [targetWithoutHeading, heading] = decoded.split("#", 2);
      const labelMatch = linkMap[targetWithoutHeading.toLowerCase()];
      const currentDir = note?.path.includes("/")
        ? note.path.slice(0, note.path.lastIndexOf("/") + 1)
        : "";
      if (/\.(pdf|pptx?|docx?)$/i.test(targetWithoutHeading)) {
        const materialCandidates = [
          targetWithoutHeading,
          currentDir && !targetWithoutHeading.startsWith(currentDir)
            ? currentDir + targetWithoutHeading
            : null,
        ].filter((value): value is string => !!value);
        for (const candidate of materialCandidates) {
          try {
            await api.vaultOpenExternal(candidate);
            return;
          } catch {
            // Try the next vault-relative material path.
          }
        }
      }
      const withExtension = (value: string) =>
        /\.(md|markdown|txt)$/i.test(value) ? value : `${value}.md`;
      const candidates = [
        labelMatch,
        targetWithoutHeading ? withExtension(targetWithoutHeading) : null,
        targetWithoutHeading && currentDir && !targetWithoutHeading.startsWith(currentDir)
          ? withExtension(currentDir + targetWithoutHeading)
          : null,
      ].filter((value, index, values): value is string =>
        !!value && values.indexOf(value) === index
      );
      let target = candidates[0] || null;
      for (const candidate of candidates) {
        try {
          await api.vaultNote(candidate);
          target = candidate;
          break;
        } catch {
          // Try the next valid Obsidian resolution (root-relative, then note-relative).
        }
      }
      if (heading) setPendingHeading(slug(heading));
      if (target) openInTab(target, newTab);
    },
    [linkMap, note?.path, openInTab],
  );

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
              className="wikilink"
              onClick={(e) => void openLinkedNote(target || name, e.ctrlKey || e.metaKey)}
            >
              {children}
            </span>
          );
        }
        const raw = decodeURIComponent(href ?? "");
        const isTauriPlaceholder = /^https?:\/\/tauri\.localhost\/?$/i.test(raw);
        const isWeb = /^(https?:|mailto:)/i.test(raw) && !isTauriPlaceholder;
        const currentDir = note?.path.includes("/")
          ? note.path.slice(0, note.path.lastIndexOf("/") + 1)
          : "";
        const relative = raw.split("#")[0].replace(/^\.\//, "");
        const noteTarget = relative
          ? relative.startsWith("/")
            ? relative.slice(1)
            : currentDir + relative
          : null;
        return (
          <a
            href={href}
            onClick={async (event) => {
              event.preventDefault();
              if (isWeb) {
                await openExternalUrl(raw);
              } else if (isTauriPlaceholder) {
                await openLinkedNote(toText(children), event.ctrlKey || event.metaKey);
              } else if (noteTarget) {
                await openLinkedNote(noteTarget, event.ctrlKey || event.metaKey);
              }
            }}
          >
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
  }, [linkMap, note?.path, openExternalUrl, openLinkedNote]);

  const rendered = useMemo(
    () => (note ? wikilinksToMd(stripFrontmatter(note.content)) : ""),
    [note],
  );

  const currentFolder = active?.includes("/")
    ? active.slice(0, active.lastIndexOf("/"))
    : "";

  const addLinksToCurrentNote = useCallback(
    async (paths: string[]) => {
      if (!note || !paths.length) return;
      const links = paths.map((item) => {
        const ext = item.split(".").pop()?.toLowerCase();
        if (ext === "md" || ext === "markdown" || ext === "txt") {
          return `[[${item.replace(/\.(md|markdown|txt)$/i, "")}]]`;
        }
        return `![[${item}]]`;
      });
      const updated = `${note.content.trimEnd()}\n\n${links.join("\n")}\n`;
      await api.vaultSaveNote(note.path, updated);
      const fresh = await api.vaultNote(note.path);
      setNote(fresh);
      setDraft(fresh.content);
      flash(`Added ${paths.length} file link${paths.length === 1 ? "" : "s"}`);
    },
    [note],
  );

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | undefined;
    import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) =>
        getCurrentWebview()
        .onDragDropEvent(async (event) => {
          if (event.payload.type === "enter" || event.payload.type === "over") {
            setDropActive(true);
            return;
          }
          if (event.payload.type === "leave") {
            setDropActive(false);
            return;
          }
          if (event.payload.type !== "drop") return;
          setDropActive(false);
          const ratio = window.devicePixelRatio || 1;
          const element = document.elementFromPoint(
            event.payload.position.x / ratio,
            event.payload.position.y / ratio,
          ) as HTMLElement | null;
          const folderElement = element?.closest("[data-folder-path]") as HTMLElement | null;
          const overContent = !!element?.closest("[data-note-drop-zone]");
          const targetFolder = folderElement?.dataset.folderPath ?? currentFolder;
          try {
            const result = await api.vaultImport(event.payload.paths, targetFolder);
            await refreshTree();
            setExpanded((previous) => new Set([...previous, targetFolder]));
            if (overContent) {
              await addLinksToCurrentNote(
                result.imported
                  .filter((item) => item.type === "file")
                  .map((item) => item.path),
              );
            } else {
              flash(`Imported ${result.count} item${result.count === 1 ? "" : "s"}`);
            }
          } catch (error) {
            flash((error as Error).message);
          }
        })
        .then((cleanup) => {
          unlisten = cleanup;
        }),
      )
      .catch((error) => flash(`File drop unavailable: ${(error as Error).message}`));
    return () => unlisten?.();
  }, [addLinksToCurrentNote, currentFolder]);

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

  const importLectureMaterials = async () => {
    if (!("__TAURI_INTERNALS__" in window)) {
      flash("Lecture-material browsing is available in the desktop app.");
      return;
    }
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        multiple: true,
        directory: false,
        title: "Add lecture PDFs or PowerPoint slides",
        filters: [
          { name: "Lecture materials", extensions: ["pdf", "pptx", "ppt"] },
        ],
      });
      const paths = Array.isArray(selected)
        ? selected.filter((value): value is string => typeof value === "string")
        : typeof selected === "string"
          ? [selected]
          : [];
      if (!paths.length) return;
      await api.vaultCreateFolder("Lecture Materials");
      const imported = await api.vaultImport(paths, "Lecture Materials");
      const scan = await api.scanVault();
      await refreshTree();
      setExpanded((previous) => new Set([...previous, "Lecture Materials"]));
      const legacyPpt = paths.some((path) => /\.ppt$/i.test(path));
      flash(
        `Added ${imported.count} lecture file${imported.count === 1 ? "" : "s"} and indexed ${scan.new + scan.updated}.` +
        (legacyPpt ? " Legacy .ppt files must be saved as .pptx or PDF to become searchable." : ""),
      );
    } catch (error) {
      flash((error as Error).message);
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

  const save = async (closeAfter = true, content = draft) => {
    if (!note) return;
    setSaving(true);
    setError(null);
    try {
      await api.vaultSaveNote(note.path, content);
      const fresh = await api.vaultNote(note.path);
      setNote(fresh);
      setDraft(fresh.content);
      if (closeAfter) setViewMode("read");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const openBookmark = (bookmark: string) => {
    const [target, heading] = bookmark.split("#", 2);
    if (heading) setPendingHeading(heading);
    openInTab(target, true);
  };

  const bookmarkHeading = (heading: string) => {
    if (!active) return;
    const target = `${active}#${heading}`;
    setBookmarks((previous) => new Set([...previous, target]));
    flash("Heading bookmarked");
  };

  const extractHeading = async (
    filename: string,
    extractedContent: string,
    updatedDocument: string,
  ) => {
    if (!note) return false;
    let target = filename.trim();
    if (!/\.(md|markdown|txt)$/i.test(target)) target += ".md";
    if (!target.includes("/") && currentFolder) target = `${currentFolder}/${target}`;
    if (target === note.path) {
      flash("Choose a different note name");
      return false;
    }
    try {
      let exists = false;
      try {
        await api.vaultNote(target);
        exists = true;
      } catch {
        exists = false;
      }
      if (exists && !window.confirm(`"${target}" already exists. Replace it?`)) return false;
      await api.vaultSaveNote(target, extractedContent);
      await api.vaultSaveNote(note.path, updatedDocument);
      const fresh = await api.vaultNote(note.path);
      setNote(fresh);
      setDraft(fresh.content);
      await refreshTree();
      flash(`Extracted heading to ${target}`);
      return true;
    } catch (error) {
      flash((error as Error).message);
      return false;
    }
  };

  const changeView = async (next: "source" | "edit" | "read") => {
    if (!note) return;
    if (next === "read" && editing && draft !== note.content) await save(false);
    setViewMode(next);
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

  const duplicatePath = async (source: string) => {
    const ext = source.match(/\.(md|markdown|txt)$/i)?.[0] ?? ".md";
    const stem = source.slice(0, -ext.length);
    let candidate = `${stem} copy${ext}`;
    let number = 2;
    while (tabs.includes(candidate)) candidate = `${stem} copy ${number++}${ext}`;
    try {
      const result = await api.vaultCopy(source, candidate);
      await refreshTree();
      openInTab(result.to, true);
      flash("Note duplicated");
    } catch (e) {
      flash((e as Error).message);
    }
  };

  const deletePath = async (target: string) => {
    if (!window.confirm(`Delete "${basename(target)}"?\nIt is moved to a backup (reversible).`)) return;
    try {
      await api.vaultDelete(target);
      setTabs((previous) =>
        previous.filter((tab) => tab !== target && !tab.startsWith(`${target}/`)),
      );
      if (activeRef.current === target || activeRef.current?.startsWith(`${target}/`)) {
        setActive(null);
      }
      setExpanded((previous) => {
        const next = new Set(previous);
        [...next].forEach((folder) => {
          if (folder === target || folder.startsWith(`${target}/`)) next.delete(folder);
        });
        return next;
      });
      await refreshTree();
      flash("Deleted (backup kept)");
    } catch (e) {
      flash((e as Error).message);
    }
  };

  const movePathToFolder = async (source: string, targetFolder: string) => {
    if (source === targetFolder || targetFolder.startsWith(`${source}/`)) return;
    try {
      const result = await api.vaultMove(source, targetFolder);
      setTabs((previous) =>
        previous.map((tab) =>
          tab === source
            ? result.to
            : tab.startsWith(`${source}/`)
              ? `${result.to}${tab.slice(source.length)}`
              : tab,
        ),
      );
      if (activeRef.current === source) setActive(result.to);
      else if (activeRef.current?.startsWith(`${source}/`)) {
        setActive(`${result.to}${activeRef.current.slice(source.length)}`);
      }
      await refreshTree();
      setExpanded((previous) => new Set([...previous, targetFolder]));
      flash(`Moved to ${targetFolder || "vault root"}`);
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const addDraggedNoteLink = async (path: string) => {
    await addLinksToCurrentNote([path]);
  };

  const startInternalDrag = (
    source: string,
    sourceType: "file" | "folder",
    startEvent: React.MouseEvent,
  ) => {
    if (startEvent.button !== 0) return;
    startEvent.preventDefault();
    const startX = startEvent.clientX;
    const startY = startEvent.clientY;
    let dragging = false;

    const inspectTarget = (x: number, y: number) => {
      const element = document.elementFromPoint(x, y) as HTMLElement | null;
      const folder = element?.closest("[data-folder-path]") as HTMLElement | null;
      return {
        target: folder?.dataset.folderPath ?? null,
        overNote: !!element?.closest("[data-note-drop-zone]"),
      };
    };

    const onMove = (event: MouseEvent) => {
      if (!dragging && Math.hypot(event.clientX - startX, event.clientY - startY) < 6) return;
      dragging = true;
      document.body.style.userSelect = "none";
      document.body.style.cursor = "grabbing";
      const target = inspectTarget(event.clientX, event.clientY);
      setInternalDrag({
        path: source,
        type: sourceType,
        x: event.clientX,
        y: event.clientY,
        ...target,
      });
    };

    const onUp = (event: MouseEvent) => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      if (!dragging) return;

      const target = inspectTarget(event.clientX, event.clientY);
      setInternalDrag(null);
      const blockClick = (clickEvent: MouseEvent) => {
        clickEvent.preventDefault();
        clickEvent.stopPropagation();
      };
      document.addEventListener("click", blockClick, { capture: true, once: true });

      if (target.overNote && sourceType === "file") {
        addDraggedNoteLink(source);
      } else if (target.target !== null) {
        movePathToFolder(source, target.target);
      }
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const toggleBookmark = () => {
    if (!active) return;
    setBookmarks((previous) => {
      const next = new Set(previous);
      next.has(active) ? next.delete(active) : next.add(active);
      return next;
    });
    flash(bookmarks.has(active) ? "Bookmark removed" : "Bookmarked");
  };

  const handleMerge = async () => {
    if (!active) return;
    const source = window.prompt("Vault-relative note to merge into this note:");
    if (!source) return;
    const deleteSource = window.confirm(
      "Delete the source note after merging?\nChoose Cancel to keep both notes.",
    );
    try {
      await api.vaultMerge(active, source, deleteSource);
      const fresh = await api.vaultNote(active);
      setNote(fresh);
      setDraft(fresh.content);
      await refreshTree();
      flash("Notes merged");
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const handleAddProperty = async () => {
    if (!active) return;
    const key = window.prompt("Property name:");
    if (!key) return;
    const value = window.prompt(`Value for ${key}:`, "") ?? "";
    try {
      await api.vaultSetProperty(active, key, value);
      const fresh = await api.vaultNote(active);
      setNote(fresh);
      setDraft(fresh.content);
      flash(`Property “${key}” saved`);
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const openVersionHistory = async () => {
    if (!active) return;
    try {
      const result = await api.vaultVersions(active);
      setVersions(result.versions);
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const restoreHistoryVersion = async (version: NoteVersion) => {
    if (!active) return;
    if (!window.confirm(`Restore the version from ${new Date(version.timestamp).toLocaleString()}?`)) return;
    try {
      await api.vaultRestoreVersion(active, version.id);
      const fresh = await api.vaultNote(active);
      setNote(fresh);
      setDraft(fresh.content);
      setVersions(null);
      flash("Version restored");
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const openSplit = (direction: "right" | "down", target = active) => {
    if (!target) return;
    setSplit(direction);
    setSplitPath(target);
    setMenuOpen(false);
  };

  const openNewWindow = async () => {
    if (!active || !("__TAURI_INTERNALS__" in window)) return;
    try {
      const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
      const label = `note-${Date.now()}`;
      new WebviewWindow(label, {
        url: `/?note=${encodeURIComponent(active)}&detached=1`,
        title: basename(active),
        width: 980,
        height: 760,
        center: true,
      });
    } catch (error) {
      flash((error as Error).message);
    }
  };

  const runFind = () => {
    if (!findText) return;
    const browserFind = (window as typeof window & {
      find?: (
        text: string,
        caseSensitive?: boolean,
        backwards?: boolean,
        wrapAround?: boolean,
        wholeWord?: boolean,
        searchInFrames?: boolean,
        showDialog?: boolean,
      ) => boolean;
    }).find;
    if (browserFind) browserFind(findText, false, false, true, false, true, false);
  };

  const replaceInNote = async (replaceAll: boolean) => {
    if (!note || !findText) return;
    const source = editing ? draft : note.content;
    const updated = replaceAll
      ? source.split(findText).join(replaceText)
      : source.replace(findText, replaceText);
    if (updated === source) {
      flash("No match found");
      return;
    }
    setReplaceUndo((history) => [...history, { path: note.path, before: source, after: updated }]);
    setReplaceRedo([]);
    setDraft(updated);
    await api.vaultSaveNote(note.path, updated);
    const fresh = await api.vaultNote(note.path);
    setNote(fresh);
    setDraft(fresh.content);
    flash(replaceAll ? "Replaced all matches" : "Replaced next match");
  };

  const applyReplaceHistory = async (direction: "undo" | "redo") => {
    const sourceStack = direction === "undo" ? replaceUndo : replaceRedo;
    const item = sourceStack[sourceStack.length - 1];
    if (!item) return;
    const content = direction === "undo" ? item.before : item.after;
    await api.vaultSaveNote(item.path, content);
    if (active === item.path) {
      const fresh = await api.vaultNote(item.path);
      setNote(fresh);
      setDraft(fresh.content);
    }
    if (direction === "undo") {
      setReplaceUndo((history) => history.slice(0, -1));
      setReplaceRedo((history) => [...history, item]);
      flash("Replace undone");
    } else {
      setReplaceRedo((history) => history.slice(0, -1));
      setReplaceUndo((history) => [...history, item]);
      flash("Replace redone");
    }
  };

  const showToc = tocOpen && !!note;

  const previewOrganization = async () => {
    setOrganizing(true);
    setError(null);
    try {
      const preview = await api.organizerPreview();
      setOrganizer(preview);
      setSelectedOrganizerMoves(
        new Set(preview.moves.map((move) => `${move.from}->${move.to}`)),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOrganizing(false);
    }
  };

  const applyOrganization = async () => {
    if (!organizer?.moves.length || !selectedOrganizerMoves.size) return;
    setOrganizing(true);
    try {
      const chosenMoves = organizer.moves.filter((move) =>
        selectedOrganizerMoves.has(`${move.from}->${move.to}`),
      );
      const result = await api.organizerApply(chosenMoves);
      setOrganizer(null);
      setSelectedOrganizerMoves(new Set());
      setTabs([]);
      setActive(null);
      setExpanded(new Set());
      await refreshTree();
      flash(`Applied ${result.applied} organization change(s).`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOrganizing(false);
    }
  };

  const previewDocumentFormat = async () => {
    if (!note) return;
    setFormatting(true);
    setError(null);
    try {
      setFormatPreview(
        await api.formatPreview(note.path, editing ? draft : note.content),
      );
    } catch (error) {
      flash((error as Error).message);
    } finally {
      setFormatting(false);
    }
  };

  const applyDocumentFormat = async () => {
    if (!note || !formatPreview) return;
    setFormatting(true);
    try {
      await api.vaultSaveNote(note.path, formatPreview.after);
      const fresh = await api.vaultNote(note.path);
      setNote(fresh);
      setDraft(fresh.content);
      setFormatPreview(null);
      flash("AI formatting applied");
    } catch (error) {
      flash((error as Error).message);
    } finally {
      setFormatting(false);
    }
  };

  const renderNotePane = (
    document: VaultNote,
    options: { primary: boolean; close?: () => void },
  ) => {
    const markdown = options.primary
      ? rendered
      : wikilinksToMd(stripFrontmatter(document.content));
    return (
      <div className="pane-group">
        {!options.primary && split !== "right" && (
          <div className="pane-tabbar">
            <div className="pane-tab active">
              <span className="tab-label">{stripExt(basename(document.path))}</span>
              <button className="tab-close" title="Close split tab" onClick={options.close}>×</button>
            </div>
            <button className="tab-add icon-btn" title="New split tab" onClick={() => {
              setSplitPath(null);
              setSplitNote(null);
            }}>+</button>
          </div>
        )}
        <section
          className={`note-pane ${align === "center" ? "reading-centered" : "reading-left"}`}
          data-note-drop-zone={options.primary ? "true" : undefined}
        >
          <div className="note-page" style={{ fontSize: `${readingZoom}%` }}>
          <div className="note-pane-heading">
            <div>
              <h2 className="page-title" style={{ margin: "0 0 4px" }}>{document.name}</h2>
              <div className="small muted">{document.path}</div>
            </div>
          </div>
          {options.primary && viewMode === "source" ? (
            <MarkdownEditor
              value={draft}
              onChange={setDraft}
              onSave={(value) => save(false, value)}
              onOpenInternal={(target) => {
                const [rawTarget, heading] = target.split("#", 2);
                const cleanTarget = rawTarget.replace(/^\.\//, "");
                const path = /\.(md|markdown|txt)$/i.test(cleanTarget)
                  ? cleanTarget
                  : `${cleanTarget}.md`;
                if (heading) setPendingHeading(slug(heading));
                openInTab(path, true);
              }}
              onBookmarkHeading={bookmarkHeading}
              onExtractHeading={extractHeading}
            />
          ) : options.primary && viewMode === "edit" ? (
            <RichMarkdownEditor
              value={draft}
              onChange={setDraft}
              onSave={(value) => save(false, value)}
              onOpenInternal={(target) => void openLinkedNote(target, true)}
              onOpenExternal={(url) => void openExternalUrl(url)}
            />
          ) : (
            <>
              <div className="md">
                <ReactMarkdown
                  remarkPlugins={mdRemarkPlugins}
                  rehypePlugins={mdRehypePlugins}
                  components={{ ...mdComponents, ...(options.primary ? components : {}) }}
                  urlTransform={(url) => url}
                >
                  {markdown}
                </ReactMarkdown>
              </div>
              {options.primary && backlinksInDocument && (
                <div className="document-backlinks">
                  <h3>Backlinks</h3>
                  {document.backlinks.length ? document.backlinks.map((backlink) => (
                    <button
                      className="linked-note"
                      key={backlink.path}
                      onClick={() => openInTab(backlink.path, false)}
                    >
                      {backlink.title}
                    </button>
                  )) : <div className="muted small">No backlinks to this note.</div>}
                </div>
              )}
            </>
          )}
          </div>
        </section>
      </div>
    );
  };

  return (
    <div className="workspace">
      <div className="ws-tree" style={{ width: treeOpen ? treeWidth : 0 }}>
        <div
          className="ws-tree-inner"
          style={{ width: treeWidth }}
          data-folder-path=""
          onDragOver={(event) => {
            if (event.dataTransfer.types.includes("application/x-study-vault-path")) {
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
            }
          }}
          onDrop={(event) => {
            if ((event.target as HTMLElement).closest("[data-folder-path]:not(.ws-tree-inner)")) return;
            const source = event.dataTransfer.getData("application/x-study-vault-path");
            if (source) movePathToFolder(source, "");
          }}
        >
          <div className="tree-toolbar">
            <button className="icon-btn" title="New note" onClick={newNote}>
              <Icon name="file-plus" />
            </button>
            <button className="icon-btn" title="New folder" onClick={newFolder}>
              <Icon name="folder-plus" />
            </button>
            <button
              className="icon-btn"
              title="Add lecture materials (PDF or PowerPoint)"
              onClick={importLectureMaterials}
            >
              <Icon name="upload" />
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
            <div className="tree-menu-wrap">
              <button
                className={`icon-btn ${bookmarkMenu ? "active" : ""}`}
                title="Bookmarks"
                onClick={() => setBookmarkMenu((open) => !open)}
              >
                <Icon name="book" />
              </button>
              {bookmarkMenu && (
                <>
                  <div className="menu-backdrop" onClick={() => setBookmarkMenu(false)} />
                  <div className="more-menu bookmark-menu">
                    <div className="bookmark-heading">Bookmarks</div>
                    {[...bookmarks].length ? [...bookmarks].map((bookmark) => (
                      <button
                        className="more-item"
                        key={bookmark}
                        onClick={() => {
                          openBookmark(bookmark);
                          setBookmarkMenu(false);
                        }}
                      >
                        <Icon name="file-text" size={14} />
                        <span className="truncate">
                          {stripExt(basename(bookmark.split("#", 1)[0]))}
                          {bookmark.includes("#") ? ` › ${bookmark.split("#", 2)[1]}` : ""}
                        </span>
                      </button>
                    )) : (
                      <div className="linked-empty muted small">No bookmarked notes yet.</div>
                    )}
                  </div>
                </>
              )}
            </div>
            <button
              className="icon-btn"
              title="AI organize vault"
              onClick={previewOrganization}
              disabled={organizing}
            >
              <Icon name="sparkles" />
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
              onContext={(event, target, type) => {
                event.preventDefault();
                setContextMenu({ path: target, type, x: event.clientX, y: event.clientY });
              }}
              onDragGesture={startInternalDrag}
              dragTarget={internalDrag?.target ?? null}
              activeRef={activeRowRef}
            />
          ) : (
            <div className="muted small">Loading…</div>
          )}
        </div>
      </div>

      {contextMenu && (
        <>
          <div className="menu-backdrop" onClick={() => setContextMenu(null)} />
          <div
            className="more-menu context-menu"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            {contextMenu.type === "file" && (
              <>
                <button className="more-item" onClick={() => { openInTab(contextMenu.path, false); setContextMenu(null); }}>
                  <Icon name="file-text" size={15} /> Open
                </button>
                <button className="more-item" onClick={() => { openInTab(contextMenu.path, true); setContextMenu(null); }}>
                  <Icon name="external-link" size={15} /> Open in new tab
                </button>
              </>
            )}
            <button className="more-item" onClick={() => { navigator.clipboard.writeText(contextMenu.path); setContextMenu(null); flash("Path copied"); }}>
              <Icon name="copy" size={15} /> Copy path
            </button>
            {contextMenu.type === "file" && (
              <button className="more-item" onClick={() => { duplicatePath(contextMenu.path); setContextMenu(null); }}>
                <Icon name="copy" size={15} /> Duplicate note
              </button>
            )}
            <div className="more-sep" />
            <button className="more-item danger" onClick={() => { deletePath(contextMenu.path); setContextMenu(null); }}>
              <Icon name="trash" size={15} /> Delete {contextMenu.type}
            </button>
          </div>
        </>
      )}
      {organizer && (
        <div className="organizer-backdrop">
          <div className="organizer-modal card">
            <div className="row">
              <div>
                <h2 className="page-title">AI organization preview</h2>
                <p className="page-sub">
                  {organizer.summary || "Review every proposed move before applying it."}
                </p>
              </div>
              <div className="grow" />
              <button onClick={() => setOrganizer(null)}>Close</button>
            </div>
            {organizer.moves.length === 0 ? (
              <div className="note-banner">The AI did not recommend any safe moves.</div>
            ) : (
              <div className="organizer-table">
                <table>
                  <thead>
                    <tr>
                      <th className="organizer-select">
                        <input
                          type="checkbox"
                          aria-label="Select all organization moves"
                          checked={
                            organizer.moves.length > 0 &&
                            selectedOrganizerMoves.size === organizer.moves.length
                          }
                          onChange={(event) =>
                            setSelectedOrganizerMoves(
                              event.target.checked
                                ? new Set(organizer.moves.map((move) => `${move.from}->${move.to}`))
                                : new Set(),
                            )
                          }
                        />
                      </th>
                      <th>Before</th><th>After</th><th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {organizer.moves.map((move) => {
                      const moveKey = `${move.from}->${move.to}`;
                      return (
                      <tr key={moveKey} className={selectedOrganizerMoves.has(moveKey) ? "" : "organizer-unselected"}>
                        <td className="organizer-select">
                          <input
                            type="checkbox"
                            aria-label={`Move ${move.from} to ${move.to}`}
                            checked={selectedOrganizerMoves.has(moveKey)}
                            onChange={(event) => {
                              setSelectedOrganizerMoves((previous) => {
                                const next = new Set(previous);
                                event.target.checked ? next.add(moveKey) : next.delete(moveKey);
                                return next;
                              });
                            }}
                          />
                        </td>
                        <td><code>{move.from}</code></td>
                        <td><code>{move.to}</code></td>
                        <td className="muted">{move.reason}</td>
                      </tr>
                    )})}
                  </tbody>
                </table>
              </div>
            )}
            <div className="row organizer-actions">
              <span className="muted small">
                {selectedOrganizerMoves.size} of {organizer.moves.length} selected. Names are preserved exactly.
              </span>
              <div className="grow" />
              <button onClick={() => setOrganizer(null)}>Cancel</button>
              <button
                className="primary"
                onClick={applyOrganization}
                disabled={organizing || selectedOrganizerMoves.size === 0}
              >
                {organizing ? "Applying…" : "Apply changes"}
              </button>
            </div>
          </div>
        </div>
      )}
      {versions && (
        <div className="organizer-backdrop">
          <div className="organizer-modal version-modal card">
            <div className="row">
              <div>
                <h2 className="page-title">Version history</h2>
                <p className="page-sub">{active}</p>
              </div>
              <div className="grow" />
              <button onClick={() => setVersions(null)}>Close</button>
            </div>
            <div className="version-list">
              {versions.length ? versions.map((version) => (
                <div className="version-entry" key={version.id}>
                  <div className="row">
                    <strong>{new Date(version.timestamp).toLocaleString()}</strong>
                    <span className="muted small">{version.size.toLocaleString()} bytes</span>
                    <div className="grow" />
                    <button onClick={() => restoreHistoryVersion(version)}>Restore</button>
                  </div>
                  <pre>{version.content.slice(0, 1200)}</pre>
                </div>
              )) : (
                <div className="note-banner">No earlier saved versions yet.</div>
              )}
            </div>
          </div>
        </div>
      )}
      {formatPreview && (
        <div className="organizer-backdrop">
          <div className="organizer-modal format-modal card">
            <div className="row">
              <div>
                <h2 className="page-title">AI formatting preview</h2>
                <p className="page-sub">
                  Review the original and formatted Markdown before applying.
                </p>
              </div>
              <div className="grow" />
              <button onClick={() => setFormatPreview(null)}>Close</button>
            </div>
            <div className="format-comparison">
              <section>
                <h3>Before</h3>
                <pre>{formatPreview.before}</pre>
              </section>
              <section>
                <h3>After</h3>
                <pre>{formatPreview.after}</pre>
              </section>
            </div>
            <div className="row organizer-actions">
              <span className="muted small">
                Model: {formatPreview.model}. Applying creates a recoverable version.
              </span>
              <div className="grow" />
              <button onClick={() => setFormatPreview(null)}>Cancel</button>
              <button
                className="primary"
                onClick={applyDocumentFormat}
                disabled={formatting || !formatPreview.changed}
              >
                {formatting ? "Applying…" : formatPreview.changed ? "Apply formatting" : "No changes"}
              </button>
            </div>
          </div>
        </div>
      )}
      {treeOpen && (
        <div className="resizer" onMouseDown={(e) => startResize(e, "tree")} />
      )}
      {internalDrag && (
        <div
          className={`drag-ghost ${internalDrag.overNote ? "linking" : ""}`}
          style={{ left: internalDrag.x + 14, top: internalDrag.y + 14 }}
        >
          {basename(internalDrag.path)}
        </div>
      )}

      <div className="ws-main">
        <div className={`tabbar ${split === "right" ? "has-right-split" : ""}`}>
          <div className="primary-tab-strip">
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
                  onClick={() => save()}
                  disabled={saving}
                >
                  Save
                </button>
              )}
              <button
                className="icon-btn"
                title="AI format document"
                onClick={previewDocumentFormat}
                disabled={formatting}
              >
                <Icon name="sparkles" size={17} />
              </button>
              <button
                className="icon-btn"
                title={align === "center" ? "Align left" : "Align center"}
                onClick={() => setAlign((a) => (a === "center" ? "left" : "center"))}
              >
                <Icon name={align === "center" ? "align-center" : "align-left"} size={17} />
              </button>
              <div className="menu-wrap">
                <button
                  className={`icon-btn note-text-size ${textSizeMenu ? "active" : ""}`}
                  title={`Text size: ${readingZoom}%`}
                  onClick={(event) => {
                    if (textSizeMenu) {
                      setTextSizeMenu(false);
                      return;
                    }
                    const rect = event.currentTarget.getBoundingClientRect();
                    setTextSizePosition({
                      top: rect.bottom + 5,
                      left: clamp(rect.right - 210, 8, window.innerWidth - 218),
                    });
                    setTextSizeMenu(true);
                  }}
                >
                  A
                </button>
                {textSizeMenu && (
                  <>
                    <div className="menu-backdrop" onClick={() => setTextSizeMenu(false)} />
                    <div
                      className="more-menu text-size-menu"
                      style={{ top: textSizePosition.top, left: textSizePosition.left }}
                    >
                      {([
                        [90, "Compact"],
                        [100, "Normal"],
                        [115, "Large"],
                        [130, "Extra large"],
                        [150, "Presentation"],
                      ] as const).map(([size, label]) => (
                        <button
                          className={`text-size-option ${readingZoom === size ? "selected" : ""}`}
                          key={size}
                          onClick={() => {
                            setReadingZoom(size);
                            setTextSizeMenu(false);
                          }}
                        >
                          <span style={{ fontSize: `${Math.round(size / 8)}px` }}>A</span>
                          <span>{label}</span>
                          <small>{size}%</small>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <button
                className={`icon-btn ${viewMode === "source" ? "active" : ""}`}
                title="Source code view"
                onClick={() => void changeView("source")}
              >
                <Icon name="code" size={17} />
              </button>
              <button
                className={`icon-btn ${viewMode === "edit" ? "active" : ""}`}
                title={viewMode === "edit" ? "Return to reading view" : "Edit view"}
                onClick={() => void changeView(viewMode === "edit" ? "read" : "edit")}
              >
                <Icon name="pencil" size={17} />
              </button>
              <button
                className={`icon-btn ${viewMode === "read" ? "active" : ""}`}
                title="Reading view"
                onClick={() => void changeView("read")}
              >
                <Icon name="book" size={17} />
              </button>
              <div className="menu-wrap">
                <button
                  className="icon-btn"
                  title="More options"
                  onClick={(event) => {
                    if (menuOpen) {
                      setMenuOpen(false);
                      return;
                    }
                    const rect = event.currentTarget.getBoundingClientRect();
                    const width = 260;
                    setMenuPosition({
                      top: rect.bottom + 4,
                      left: clamp(rect.right - width, 8, window.innerWidth - width - 8),
                    });
                    setMenuOpen(true);
                  }}
                >
                  <Icon name="more-vertical" size={17} />
                </button>
                {menuOpen && (
                  <>
                    <div className="menu-backdrop" onClick={() => setMenuOpen(false)} />
                    <div
                      className="more-menu note-actions-menu"
                      style={{ top: menuPosition.top, left: menuPosition.left }}
                    >
                      <button className="more-item" onClick={() => { setBacklinksInDocument((value) => !value); setMenuOpen(false); }}>
                        <Icon name="graph" size={15} /> Backlinks in document
                        {backlinksInDocument && <span className="menu-check">✓</span>}
                      </button>
                      <button className="more-item" onClick={() => { void changeView("read"); setMenuOpen(false); }}>
                        <Icon name="book" size={15} /> Reading view
                      </button>
                      <div className="more-sep" />
                      <button className="more-item" onClick={() => openSplit("right")}>
                        <Icon name="panel-right" size={15} /> Split right
                      </button>
                      <button className="more-item" onClick={() => openSplit("down")}>
                        <Icon name="panel-left" size={15} /> Split down
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); openNewWindow(); }}>
                        <Icon name="external-link" size={15} /> Open in new window
                      </button>
                      <div className="more-sep" />
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleRename(); }}>
                        <Icon name="pencil" size={15} /> Rename…
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); toggleBookmark(); }}>
                        <Icon name="book" size={15} /> {active && bookmarks.has(active) ? "Remove bookmark" : "Bookmark…"}
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleMerge(); }}>
                        <Icon name="layers" size={15} /> Merge entire file with…
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleAddProperty(); }}>
                        <Icon name="file-plus" size={15} /> Add file property
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleExportPdf(); }}>
                        <Icon name="download" size={15} /> Export to PDF…
                      </button>
                      <div className="more-sep" />
                      <button className="more-item" onClick={() => { setFindMode("find"); setMenuOpen(false); }}>
                        <Icon name="search" size={15} /> Find…
                      </button>
                      <button className="more-item" onClick={() => { setFindMode("replace"); setMenuOpen(false); }}>
                        <Icon name="pencil" size={15} /> Replace…
                      </button>
                      <div className="more-sep" />
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleCopyPath(); }}>
                        <Icon name="copy" size={15} /> Copy path
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); openVersionHistory(); }}>
                        <Icon name="reveal" size={15} /> Open version history
                      </button>
                      <button className="more-item" onClick={() => setLinkedMenu((value) => !value)}>
                        <Icon name="graph" size={15} /> Open linked view
                      </button>
                      {linkedMenu && (
                        <div className="linked-view-menu">
                          {[...(note?.links ?? []).filter((item) => item.path), ...(note?.backlinks ?? [])]
                            .slice(0, 12)
                            .map((item) => (
                              <button
                                className="more-item"
                                key={item.path}
                                onClick={() => {
                                  if (item.path) openSplit("right", item.path);
                                  setLinkedMenu(false);
                                }}
                              >
                                <span className="truncate">{"title" in item ? item.title : item.name}</span>
                              </button>
                            ))}
                          {!(note?.links.some((item) => item.path) || note?.backlinks.length) && (
                            <div className="small muted linked-empty">No linked notes</div>
                          )}
                        </div>
                      )}
                      <div className="more-sep" />
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleOpenExternal(); }}>
                        <Icon name="external-link" size={15} /> Open in default app
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); handleReveal(); }}>
                        <Icon name="reveal" size={15} /> Show in system explorer
                      </button>
                      <button className="more-item" onClick={() => { setMenuOpen(false); reveal(); }}>
                        <Icon name="folder" size={15} /> Reveal file in navigation
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
          {split === "right" && (
            <div className="right-split-tab-strip">
              {splitNote ? (
                <div className="tab active" title={splitNote.path}>
                  <span className="tab-label">{stripExt(basename(splitNote.path))}</span>
                  <button
                    className="tab-close"
                    title="Close split tab"
                    onClick={() => {
                      setSplit(null);
                      setSplitPath(null);
                    }}
                  >×</button>
                </div>
              ) : (
                <div className="tab newtab active"><span className="tab-label">New tab</span></div>
              )}
              <button
                className="tab-add icon-btn"
                title="New split tab"
                onClick={() => {
                  setSplitPath(null);
                  setSplitNote(null);
                }}
              >+</button>
            </div>
          )}
        </div>

        {findMode && (
          <div className="find-bar">
            <input
              autoFocus
              value={findText}
              onChange={(event) => setFindText(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && runFind()}
              placeholder="Find in note"
            />
            {findMode === "replace" && (
              <input
                value={replaceText}
                onChange={(event) => setReplaceText(event.target.value)}
                placeholder="Replace with"
              />
            )}
            <button onClick={runFind}>Next</button>
            {findMode === "replace" && (
              <>
                <button onClick={() => replaceInNote(false)}>Replace</button>
                <button onClick={() => replaceInNote(true)}>Replace all</button>
                <button disabled={!replaceUndo.length} onClick={() => applyReplaceHistory("undo")}>Undo</button>
                <button disabled={!replaceRedo.length} onClick={() => applyReplaceHistory("redo")}>Redo</button>
              </>
            )}
            <button className="icon-btn" onClick={() => setFindMode(null)}>×</button>
          </div>
        )}

        <div className={`ws-content ${dropActive ? "drop-active" : ""}`}>
          {banner && <div className="note-banner">{banner}</div>}
          {error && <div className="warn-banner">{error}</div>}
          {dropActive && (
            <div className="drop-overlay">
              Drop files to import them into {currentFolder || "the vault"}
            </div>
          )}
          {isNewTab(active) ? (
            <NewTabPicker onPick={pickInNewTab} />
          ) : !note ? (
            <div className="muted">Select a note from the tree, or press + for a new tab.</div>
          ) : (
            <div className={`note-panes ${split ? `split-${split}` : ""}`}>
              {renderNotePane(note, { primary: true })}
              {split && splitNote && (
                <>
                  <div className="pane-divider" />
                  {renderNotePane(splitNote, {
                    primary: false,
                    close: () => {
                      setSplit(null);
                      setSplitPath(null);
                    },
                  })}
                </>
              )}
              {split && !splitNote && (
                <>
                  <div className="pane-divider" />
                  <div className="pane-group">
                    {split !== "right" && <div className="pane-tabbar">
                      <div className="pane-tab newtab active">New tab</div>
                      <button className="tab-close icon-btn" title="Close split" onClick={() => {
                        setSplit(null);
                        setSplitPath(null);
                      }}>×</button>
                    </div>}
                    <div className="note-pane">
                      <NewTabPicker onPick={(selected) => setSplitPath(selected)} />
                    </div>
                  </div>
                </>
              )}
            </div>
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
