// The notes workspace (Obsidian-style): file tree, tabs, reading view and
// editors, outline and mentions, plus file actions. This file wires the parts
// in ./notes together and owns the open note, its draft and saving.

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { stripFrontmatter, wikilinksToMd } from "../markdown";
import type { MentionGroup, MentionSpan, NoteMentions, TreeNode, VaultNote } from "../types";
import { BacklinkReviewDialog, useBacklinkReview } from "./notes/BacklinkReviewDialog";
import { useDesktopFileDrop, useTreeDrag } from "./notes/dragDrop";
import { FileTree, TreeContextMenu, type TreeContext } from "./notes/FileTree";
import { FindBar, useFindReplace } from "./notes/FindBar";
import { FormatPreviewDialog, useFormatPreview } from "./notes/FormatPreviewDialog";
import { NewTabPicker } from "./notes/NewTabPicker";
import { NotePane, preloadEditors, type PaneEditing } from "./notes/NotePane";
import { OrganizerDialog, useOrganizer } from "./notes/OrganizerDialog";
import { OutlinePanel } from "./notes/OutlinePanel";
import {
  ancestorsOf,
  basename,
  collectFolders,
  folderOf,
  isNewTab,
  isTextNote,
  noteNames,
  slug,
  stripExt,
} from "./notes/paths";
import { useNoteTabs, usePanelWidths, useStoredNumber, useStoredSet, useStoredState } from "./notes/state";
import { TabBar, type NoteActions, type ViewMode } from "./notes/TabBar";
import { TranslationOverlays, useSelectionTranslation } from "./notes/TranslationLayer";
import type { InlineNoteTranslation } from "./notes/translation";
import { VersionHistoryDialog, useVersionHistory } from "./notes/VersionHistoryDialog";
import { useWikiComponents } from "./notes/wikiComponents";

const LocalGraph = lazy(() => import("../LocalGraph").then((m) => ({ default: m.LocalGraph })));

const withExtension = (value: string) => (isTextNote(value) ? value : `${value}.md`);

export function NotesPage({
  path,
  openSeq = 0,
  tocOpen,
  treeOpen,
  detached = false,
  onActiveChange,
}: {
  path: string | null;
  /** Bumped on every open request, so re-opening the same note re-focuses it. */
  openSeq?: number;
  tocOpen: boolean;
  treeOpen: boolean;
  detached?: boolean;
  /** Reports the note shown in the active tab (null for none / a new tab). */
  onActiveChange?: (path: string | null) => void;
}) {
  // ---- Tree, tabs, layout -------------------------------------------------
  const [tree, setTree] = useState<TreeNode | null>(null);
  const {
    tabs, setTabs, active, setActive, activeRef, openNewTab, pickInNewTab, openInTab, closeTab,
  } = useNoteTabs({ detached, path });
  const [expanded, setExpanded] = useStoredSet("ws.expanded");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const { treeWidth, tocWidth, startResize } = usePanelWidths();
  const [align, setAlign] = useStoredState<"left" | "center">(
    "ws.align",
    (raw) => (raw as "left" | "center") || "left",
    (value) => value,
  );
  const [readingZoom, setReadingZoom] = useStoredNumber("ws.readingZoom", 100);
  const [bookmarks, setBookmarks] = useStoredSet("ws.bookmarks");
  const [backlinksInDocument, setBacklinksInDocument] = useStoredState(
    "ws.backlinksInDocument",
    (raw) => raw === "true",
    String,
  );
  const activeRowRef = useRef<HTMLDivElement>(null);

  // ---- The open note --------------------------------------------------------
  const [note, setNote] = useState<VaultNote | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("read");
  const editing = viewMode !== "read";
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [pendingHeading, setPendingHeading] = useState<string | null>(null);
  const [mentions, setMentions] = useState<NoteMentions | null>(null);
  const [contextMenu, setContextMenu] = useState<TreeContext | null>(null);
  const [inlineTranslation, setInlineTranslation] = useState<InlineNoteTranslation | null>(null);
  const [wholeNoteTranslating, setWholeNoteTranslating] = useState(false);
  const [split, setSplit] = useState<"right" | "down" | null>(null);
  const [splitPath, setSplitPath] = useState<string | null>(null);
  const [splitNote, setSplitNote] = useState<VaultNote | null>(null);
  const [showLocalGraph, setShowLocalGraph] = useState(false);

  const flash = (m: string) => {
    setBanner(m);
    setTimeout(() => setBanner(null), 4000);
  };
  const refreshTree = () => api.vaultTree().then(setTree);
  /** Re-read a note from disk into the page (and the draft). */
  const reload = async (notePath: string) => {
    const fresh = await api.vaultNote(notePath);
    setNote(fresh);
    setDraft(fresh.content);
  };
  const currentFolder = active?.includes("/") ? active.slice(0, active.lastIndexOf("/")) : "";

  // Warm the editors once the page has settled, so the first edit is instant.
  useEffect(() => {
    const timer = window.setTimeout(preloadEditors, 2500);
    return () => window.clearTimeout(timer);
  }, []);

  const onActiveChangeRef = useRef(onActiveChange);
  onActiveChangeRef.current = onActiveChange;
  useEffect(() => {
    onActiveChangeRef.current?.(active && !isNewTab(active) ? active : null);
  }, [active]);

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
  }, [path, openSeq, openInTab]);

  // Load the active note (skip empty "new tab" placeholders).
  useEffect(() => {
    // Anything typed but not yet autosaved must survive a note/tab switch.
    if (note && draft !== note.content) {
      void api.vaultSaveNote(note.path, draft).catch(() => undefined);
    }
    if (!active || isNewTab(active)) {
      setNote(null);
      setInlineTranslation(null);
      return;
    }
    setViewMode("read");
    setInlineTranslation(null);
    setError(null);
    setExpanded((prev) => new Set([...prev, ...ancestorsOf(active)]));

    // Text first, links second. Both requests start together; if the links
    // arrive within a moment they render with the text in one pass, otherwise
    // the text shows straight away and the links are merged in when ready.
    let alive = true;
    const LINK_GRACE_MS = 120;
    const linksRequest = api.vaultNoteLinks(active);
    api
      .vaultNote(active, { links: false })
      .then((n) => {
        if (!alive) return;
        let shown = false;
        const show = (links?: Pick<VaultNote, "links" | "backlinks">) => {
          shown = true;
          setNote({ ...n, ...(links ?? {}), links_loaded: Boolean(links) });
          setDraft(n.content);
        };
        const timer = window.setTimeout(() => alive && !shown && show(), LINK_GRACE_MS);
        linksRequest
          .then((l) => {
            if (!alive) return;
            if (!shown) {
              window.clearTimeout(timer);
              show(l);
            } else {
              setNote((current) =>
                current && current.path === n.path
                  ? { ...current, links: l.links, backlinks: l.backlinks, links_loaded: true }
                  : current,
              );
            }
          })
          .catch(() => {
            if (alive && !shown) {
              window.clearTimeout(timer);
              show();
            }
          });
      })
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, [active]);

  useEffect(() => {
    if (!splitPath) {
      setSplitNote(null);
      return;
    }
    api.vaultNote(splitPath).then(setSplitNote).catch(() => setSplitNote(null));
  }, [splitPath]);

  // A note being translated in the background: poll until it's done.
  useEffect(() => {
    if (!note || editing || !note.content.includes('translated_status: "running"')) {
      return;
    }
    const timer = window.setInterval(() => {
      api
        .vaultNote(note.path)
        .then((fresh) => {
          setNote(fresh);
          setDraft(fresh.content);
          if (!fresh.content.includes('translated_status: "running"')) {
            void refreshTree();
            flash(
              fresh.content.includes('translated_status: "failed"')
                ? "Translation failed. The note has the error details."
                : "Translation finished.",
            );
          }
        })
        .catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [editing, note]);

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

  // ---- Links ----------------------------------------------------------------
  const linkMap = useMemo(() => {
    const m: Record<string, string | null> = {};
    note?.links.forEach((l) => (m[l.name.toLowerCase()] = l.path));
    return m;
  }, [note]);

  useEffect(() => {
    setMentions(null);
    if (!note?.path) return;
    let alive = true;
    api
      .vaultBacklinks(note.path)
      .then((m) => alive && setMentions(m))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [note?.path]);

  // Every note name in the vault, for [[ link autocomplete in the editors.
  const linkTargets = useMemo(() => noteNames(tree), [tree]);

  const linkUnlinkedMention = async (group: MentionGroup, m: MentionSpan) => {
    if (!note) return;
    try {
      await api.vaultLinkMention({
        source_path: group.path,
        target_path: note.path,
        line: m.line,
        start: m.start,
        end: m.end,
      });
      flash(`Linked mention in ${group.title}.`);
      setMentions(await api.vaultBacklinks(note.path));
    } catch (e) {
      flash(String((e as Error).message ?? e));
    }
  };

  const openExternalUrl = useCallback(async (url: string) => {
    if ("__TAURI_INTERNALS__" in window) {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
    } else {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }, []);

  /**
   * Follow a link from the open note: lecture files open in their app; notes
   * resolve like Obsidian (link map, vault root, then next to this note), and
   * an unresolved note link creates the note beside this one.
   */
  const openLinkedNote = useCallback(
    async (rawTarget: string, newTab = true) => {
      if (!rawTarget) return;
      const decoded = decodeURIComponent(rawTarget)
        .replace(/^wikilink:/i, "")
        .replace(/^https?:\/\/tauri\.localhost\/?/i, "")
        .replace(/^\.\//, "");
      const [targetWithoutHeading, heading] = decoded.split("#", 2);
      const labelMatch = linkMap[targetWithoutHeading.toLowerCase()];
      const currentDir = folderOf(note?.path);
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
      const candidates = [
        labelMatch,
        targetWithoutHeading ? withExtension(targetWithoutHeading) : null,
        targetWithoutHeading && currentDir && !targetWithoutHeading.startsWith(currentDir)
          ? withExtension(currentDir + targetWithoutHeading)
          : null,
      ].filter((value, index, values): value is string =>
        !!value && values.indexOf(value) === index
      );
      let target: string | null = null;
      for (const candidate of candidates) {
        try {
          await api.vaultNote(candidate, { links: false }); // existence check only
          target = candidate;
          break;
        } catch {
          // Try the next valid Obsidian resolution (root-relative, then note-relative).
        }
      }
      if (!target && targetWithoutHeading) {
        // Unresolved note link: create it beside the current note (Obsidian-style).
        const ext = /\.([a-z0-9]{1,6})$/i
          .exec(targetWithoutHeading)?.[1]
          ?.toLowerCase();
        if (ext && !["md", "markdown", "txt"].includes(ext)) return;
        const newPath = withExtension(currentDir + targetWithoutHeading);
        try {
          await api.vaultSaveNote(newPath, `# ${stripExt(targetWithoutHeading)}\n\n`);
          await refreshTree();
          flash(`Created "${newPath}".`);
          target = newPath;
        } catch (e) {
          flash((e as Error).message);
          return;
        }
      }
      if (heading) setPendingHeading(slug(heading));
      if (target) openInTab(target, newTab);
    },
    [linkMap, note?.path, openInTab],
  );

  const components = useWikiComponents({
    linkMap,
    notePath: note?.path,
    openLinkedNote,
    openExternalUrl,
  });

  const rendered = useMemo(
    () => (note ? wikilinksToMd(stripFrontmatter(note.content)) : ""),
    [note],
  );

  /** Append [[links]] (notes) or ![[embeds]] (other files) to the open note. */
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
      await reload(note.path);
      flash(`Added ${paths.length} file link${paths.length === 1 ? "" : "s"}`);
    },
    [note],
  );

  const dropActive = useDesktopFileDrop({
    currentFolder,
    onImported: async (folder) => {
      await refreshTree();
      setExpanded((previous) => new Set([...previous, folder]));
    },
    onLinkIntoNote: addLinksToCurrentNote,
    flash,
  });

  // ---- Tree actions -----------------------------------------------------------
  const toggleFolder = (p: string) =>
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(p) ? n.delete(p) : n.add(p);
      return n;
    });

  const newNote = async () => {
    const name = window.prompt("New note (optionally Folder/Name):");
    if (!name) return;
    const p = withExtension(name.trim());
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
      const legacyPpt = paths.some((item) => /\.ppt$/i.test(item));
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

  /** Expand the tree down to the active note and scroll it into view. */
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

  const treeDrag = useTreeDrag({
    onMoveToFolder: (source, folder) => void movePathToFolder(source, folder),
    onLinkIntoNote: (source) => void addLinksToCurrentNote([source]),
  });

  const openBookmark = (bookmark: string) => {
    const [target, heading] = bookmark.split("#", 2);
    if (heading) setPendingHeading(heading);
    openInTab(target, true);
  };

  // ---- Saving -----------------------------------------------------------------
  const save = async (closeAfter = true, content = draft) => {
    if (!note) return;
    setSaving(true);
    setError(null);
    try {
      await api.vaultSaveNote(note.path, content);
      const fresh = await api.vaultNote(note.path);
      setNote(fresh);
      // Keep typing that landed while the save was in flight.
      setDraft((current) => (current === content ? fresh.content : current));
      if (closeAfter) setViewMode("read");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveRef = useRef(save);
  saveRef.current = save;
  const dirty = !!note && editing && draft !== note.content;

  // Autosave: after ~1.2s of quiet typing the note saves itself (Obsidian-style).
  useEffect(() => {
    if (!dirty || saving) return;
    const timer = window.setTimeout(() => void saveRef.current(false), 1200);
    return () => window.clearTimeout(timer);
  }, [dirty, draft, editing, note, saving]);

  // Don't let a window close/refresh silently drop unsaved edits.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Ctrl+S anywhere on the page (the editors handle their own shortcut).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
      const el = event.target as HTMLElement | null;
      if (el?.closest(".cm-editor, .rich-editor-shell")) return;
      if (!dirty) return;
      event.preventDefault();
      void saveRef.current(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty]);

  // Last-resort flush: save pending edits if the page unmounts mid-edit.
  const noteRef = useRef(note);
  const draftRef = useRef(draft);
  noteRef.current = note;
  draftRef.current = draft;
  useEffect(
    () => () => {
      const last = noteRef.current;
      if (last && draftRef.current !== last.content) {
        void api.vaultSaveNote(last.path, draftRef.current).catch(() => undefined);
      }
    },
    [],
  );

  const changeView = async (next: ViewMode) => {
    if (!note) return;
    if (next === "read" && editing && draft !== note.content) await save(false);
    setViewMode(next);
  };

  // ---- Editor callbacks ---------------------------------------------------------
  const bookmarkHeading = (heading: string) => {
    if (!active) return;
    const target = `${active}#${heading}`;
    setBookmarks((previous) => new Set([...previous, target]));
    flash("Heading bookmarked");
  };

  /** Move a heading's section into its own note (from the source editor). */
  const extractHeading = async (
    filename: string,
    extractedContent: string,
    updatedDocument: string,
  ) => {
    if (!note) return false;
    let target = withExtension(filename.trim());
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
      await reload(note.path);
      await refreshTree();
      flash(`Extracted heading to ${target}`);
      return true;
    } catch (error) {
      flash((error as Error).message);
      return false;
    }
  };

  const paneEditing: PaneEditing = {
    viewMode,
    draft,
    setDraft,
    save: (value) => void save(false, value),
    openFromSource: (target) => {
      const [rawTarget, heading] = target.split("#", 2);
      const cleanTarget = rawTarget.replace(/^\.\//, "");
      if (heading) setPendingHeading(slug(heading));
      openInTab(withExtension(cleanTarget), true);
    },
    openLinkedNote: (target, newTab) => void openLinkedNote(target, newTab),
    openExternalUrl: (url) => void openExternalUrl(url),
    bookmarkHeading,
    extractHeading,
    linkTargets,
  };

  // ---- Dialogs and panels ---------------------------------------------------------
  const translation = useSelectionTranslation({ onMenuOpen: () => setContextMenu(null) });

  const organizer = useOrganizer({
    setError,
    onApplied: async (applied) => {
      setTabs([]);
      setActive(null);
      setExpanded(new Set());
      await refreshTree();
      flash(`Applied ${applied} organization change(s).`);
    },
  });

  const review = useBacklinkReview({
    flash,
    onLinked: async (target, group) => {
      if (note?.path === target.path) setMentions(await api.vaultBacklinks(target.path));
      if (active === group.path) await reload(group.path);
    },
  });

  const history = useVersionHistory({ path: active, flash, reload });

  const format = useFormatPreview({
    path: note?.path ?? null,
    currentContent: () => (editing ? draft : note?.content ?? ""),
    setError,
    flash,
    reload,
  });

  const findReplace = useFindReplace({
    note,
    active,
    source: () => (editing ? draft : note?.content ?? ""),
    setDraft,
    flash,
    reload,
  });

  const translateWholeNote = async () => {
    if (!note) return;
    if (editing && draft !== note.content) {
      flash("Save this note before translating it");
      return;
    }
    translation.closeAll();
    setInlineTranslation(null);
    setWholeNoteTranslating(true);
    flash("Translating note into a new Chinese Markdown file...");
    try {
      const result = await api.translateWholeNote(note.path, true);
      await refreshTree();
      setExpanded((previous) => new Set([...previous, ...ancestorsOf(result.path)]));
      openInTab(result.path, true);
      flash(
        result.status === "running"
          ? `Created translated note: ${result.title}. Translation is continuing in the background.`
          : `Created translated note: ${result.title}`,
      );
    } catch (error) {
      flash((error as Error).message);
    } finally {
      setWholeNoteTranslating(false);
    }
  };

  const openSplit = (direction: "right" | "down", target = active) => {
    if (!target) return;
    setSplit(direction);
    setSplitPath(target);
  };
  const closeSplit = () => {
    setSplit(null);
    setSplitPath(null);
  };
  const newSplitTab = () => {
    setSplitPath(null);
    setSplitNote(null);
  };

  // ---- Actions on the active note (tab bar and ⋮ menu) ----------------------------
  const actionable = !!note && !isNewTab(active);

  /** Run `action` on the active note, reporting failures in the banner. */
  const onActive = (action: (target: string) => Promise<unknown>) => async () => {
    if (!actionable || !active) return;
    try {
      await action(active);
    } catch (e) {
      flash((e as Error).message);
    }
  };

  const actions: NoteActions = {
    save: () => void save(),
    translate: () => void translateWholeNote(),
    format: () => void format.open(),
    toggleAlign: () => setAlign((a) => (a === "center" ? "left" : "center")),
    setZoom: setReadingZoom,
    changeView: (mode) => void changeView(mode),
    toggleBacklinksInDocument: () => setBacklinksInDocument((value) => !value),
    reviewMentions: () => review.start(note?.name ?? ""),
    split: openSplit,
    openNewWindow: async () => {
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
    },
    rename: onActive(async (current) => {
      const name = window.prompt("Rename note to:", basename(current));
      if (!name || name === basename(current)) return;
      const to = withExtension(folderOf(current) + name);
      const r = await api.vaultRename(current, to);
      setTabs((p) => p.map((x) => (x === current ? r.to : x)));
      setActive(r.to);
      await refreshTree();
      if (r.links_updated > 0) {
        flash(`Updated links in ${r.links_updated} note${r.links_updated === 1 ? "" : "s"}.`);
      }
    }),
    toggleBookmark: () => {
      if (!active) return;
      setBookmarks((previous) => {
        const next = new Set(previous);
        next.has(active) ? next.delete(active) : next.add(active);
        return next;
      });
      flash(bookmarks.has(active) ? "Bookmark removed" : "Bookmarked");
    },
    merge: async () => {
      if (!active) return;
      const source = window.prompt("Vault-relative note to merge into this note:");
      if (!source) return;
      const deleteSource = window.confirm(
        "Delete the source note after merging?\nChoose Cancel to keep both notes.",
      );
      try {
        await api.vaultMerge(active, source, deleteSource);
        await reload(active);
        await refreshTree();
        flash("Notes merged");
      } catch (error) {
        flash((error as Error).message);
      }
    },
    addProperty: async () => {
      if (!active) return;
      const key = window.prompt("Property name:");
      if (!key) return;
      const value = window.prompt(`Value for ${key}:`, "") ?? "";
      try {
        await api.vaultSetProperty(active, key, value);
        await reload(active);
        flash(`Property “${key}” saved`);
      } catch (error) {
        flash((error as Error).message);
      }
    },
    exportPdf: onActive(async (current) => {
      const r = await api.vaultExportPdf(current);
      flash(`Exported PDF: ${r.pdf}`);
      const rel = `StudyCopilot/Exports/${stripExt(basename(current))}.pdf`;
      api.vaultOpenExternal(rel).catch(() => {});
    }),
    find: (mode) => findReplace.setMode(mode),
    copyPath: async () => {
      if (!actionable || !active) return;
      try {
        await navigator.clipboard.writeText(active);
        flash("Path copied");
      } catch {
        flash(active);
      }
    },
    versionHistory: () => void history.open(),
    localGraph: () => setShowLocalGraph(true),
    openExternal: onActive((current) => api.vaultOpenExternal(current)),
    revealInSystem: onActive((current) => api.vaultReveal(current)),
    revealInTree: reveal,
    remove: onActive(async (current) => {
      if (!window.confirm(`Delete "${basename(current)}"?\nIt is moved to a backup (reversible).`)) return;
      await api.vaultDelete(current);
      closeTab(current);
      await refreshTree();
      flash("Deleted (backup kept)");
    }),
  };

  const showToc = tocOpen && !!note;
  const paneProps = {
    split,
    align,
    readingZoom,
    rendered,
    components,
    inlineTranslation,
    editing: paneEditing,
    translation,
    backlinksInDocument,
    onOpenBacklink: (p: string) => openInTab(p, false),
    onNewSplitTab: newSplitTab,
  };

  return (
    <div className="workspace">
      <FileTree
        tree={tree}
        open={treeOpen}
        width={treeWidth}
        active={active}
        expanded={expanded}
        sortDir={sortDir}
        allExpanded={allExpanded}
        bookmarks={bookmarks}
        organizing={organizer.busy}
        dragTarget={treeDrag.drag?.target ?? null}
        activeRowRef={activeRowRef}
        onToggle={toggleFolder}
        onOpen={openInTab}
        onContext={setContextMenu}
        onDragGesture={treeDrag.start}
        onDropToRoot={(source) => void movePathToFolder(source, "")}
        onNewNote={newNote}
        onNewFolder={newFolder}
        onImportLectures={importLectureMaterials}
        onToggleSort={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
        onReveal={reveal}
        onToggleExpandAll={toggleExpandAll}
        onOpenBookmark={openBookmark}
        onOrganize={organizer.open}
      />

      {contextMenu && (
        <TreeContextMenu
          context={contextMenu}
          onClose={() => setContextMenu(null)}
          onOpen={openInTab}
          onCopyPath={(p) => {
            navigator.clipboard.writeText(p);
            flash("Path copied");
          }}
          onDuplicate={(p) => void duplicatePath(p)}
          onDelete={(p) => void deletePath(p)}
        />
      )}
      <TranslationOverlays translation={translation} onCopied={() => flash("Translation copied")} />
      <OrganizerDialog organizer={organizer} />
      <BacklinkReviewDialog review={review} onOpenNote={(p) => openInTab(p, true)} />
      <VersionHistoryDialog history={history} path={active} />
      <FormatPreviewDialog format={format} />
      {treeOpen && (
        <div className="resizer" onMouseDown={(e) => startResize(e, "tree")} />
      )}
      {treeDrag.drag && (
        <div
          className={`drag-ghost ${treeDrag.drag.overNote ? "linking" : ""}`}
          style={{ left: treeDrag.drag.x + 14, top: treeDrag.drag.y + 14 }}
        >
          {basename(treeDrag.drag.path)}
        </div>
      )}

      <div className="ws-main">
        <TabBar
          tabs={tabs}
          active={active}
          onSelect={setActive}
          onClose={closeTab}
          onNewTab={openNewTab}
          note={note}
          actionable={actionable}
          dirty={dirty}
          saving={saving}
          translating={wholeNoteTranslating}
          formatting={format.busy}
          align={align}
          readingZoom={readingZoom}
          viewMode={viewMode}
          backlinksInDocument={backlinksInDocument}
          bookmarked={!!active && bookmarks.has(active)}
          actions={actions}
          split={split}
          splitNote={splitNote}
          onCloseSplit={closeSplit}
          onNewSplitTab={newSplitTab}
        />
        <FindBar findReplace={findReplace} />

        <div className={`ws-content ${dropActive ? "drop-active" : ""}`}>
          {wholeNoteTranslating && (
            <div className="note-banner">Translating note into a new Chinese Markdown file...</div>
          )}
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
              <NotePane note={note} primary {...paneProps} />
              {split && splitNote && (
                <>
                  <div className="pane-divider" />
                  <NotePane note={splitNote} primary={false} onClose={closeSplit} {...paneProps} />
                </>
              )}
              {split && !splitNote && (
                <>
                  <div className="pane-divider" />
                  <div className="pane-group">
                    {split !== "right" && <div className="pane-tabbar">
                      <div className="pane-tab newtab active">New tab</div>
                      <button className="tab-close icon-btn" title="Close split" onClick={closeSplit}>×</button>
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
      <OutlinePanel
        open={showToc}
        width={tocWidth}
        note={note}
        mentions={mentions}
        onOpen={openInTab}
        onLinkMention={(group, m) => void linkUnlinkedMention(group, m)}
      />
      {showLocalGraph && active && (
        <Suspense fallback={null}>
          <LocalGraph
            path={active}
            title={stripExt(basename(active))}
            onOpen={(p) => {
              openInTab(p, true);
              setShowLocalGraph(false);
            }}
            onClose={() => setShowLocalGraph(false)}
          />
        </Suspense>
      )}
    </div>
  );
}
