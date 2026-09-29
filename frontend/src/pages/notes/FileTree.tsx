// The left-hand file tree: toolbar (new note/folder, import, sort, reveal,
// expand all, bookmarks, AI organize), the folder tree itself, and the
// right-click menu for tree rows.

import { useState } from "react";
import { Icon } from "../../icons";
import type { TreeNode } from "../../types";
import { basename, sortChildren, stripExt } from "./paths";

export type TreeContext = {
  path: string;
  type: "file" | "folder";
  x: number;
  y: number;
};

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

export function FileTree({
  tree,
  open,
  width,
  active,
  expanded,
  sortDir,
  allExpanded,
  bookmarks,
  organizing,
  dragTarget,
  activeRowRef,
  onToggle,
  onOpen,
  onContext,
  onDragGesture,
  onDropToRoot,
  onNewNote,
  onNewFolder,
  onImportLectures,
  onToggleSort,
  onReveal,
  onToggleExpandAll,
  onOpenBookmark,
  onOrganize,
}: {
  tree: TreeNode | null;
  open: boolean;
  width: number;
  active: string | null;
  expanded: Set<string>;
  sortDir: "asc" | "desc";
  allExpanded: boolean;
  bookmarks: Set<string>;
  organizing: boolean;
  dragTarget: string | null;
  activeRowRef: React.RefObject<HTMLDivElement>;
  onToggle: (path: string) => void;
  onOpen: (path: string, newTab: boolean) => void;
  onContext: (context: TreeContext) => void;
  onDragGesture: NodeProps["onDragGesture"];
  onDropToRoot: (source: string) => void;
  onNewNote: () => void;
  onNewFolder: () => void;
  onImportLectures: () => void;
  onToggleSort: () => void;
  onReveal: () => void;
  onToggleExpandAll: () => void;
  onOpenBookmark: (bookmark: string) => void;
  onOrganize: () => void;
}) {
  const [bookmarkMenu, setBookmarkMenu] = useState(false);
  return (
    <div className="ws-tree" style={{ width: open ? width : 0 }}>
      <div
        className="ws-tree-inner"
        style={{ width }}
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
          if (source) onDropToRoot(source);
        }}
      >
        <div className="tree-toolbar">
          <button className="icon-btn" title="New note" onClick={onNewNote}>
            <Icon name="file-plus" />
          </button>
          <button className="icon-btn" title="New folder" onClick={onNewFolder}>
            <Icon name="folder-plus" />
          </button>
          <button
            className="icon-btn"
            title="Add lecture materials (PDF or PowerPoint)"
            onClick={onImportLectures}
          >
            <Icon name="upload" />
          </button>
          <button
            className="icon-btn"
            title={`Sort ${sortDir === "asc" ? "Z→A" : "A→Z"}`}
            onClick={onToggleSort}
          >
            <Icon name="sort" />
          </button>
          <button className="icon-btn" title="Reveal current note" onClick={onReveal}>
            <Icon name="reveal" />
          </button>
          <button
            className="icon-btn"
            title={allExpanded ? "Collapse all" : "Expand all"}
            onClick={onToggleExpandAll}
          >
            <Icon name={allExpanded ? "collapse" : "expand"} />
          </button>
          <div className="tree-menu-wrap">
            <button
              className={`icon-btn ${bookmarkMenu ? "active" : ""}`}
              title="Bookmarks"
              onClick={() => setBookmarkMenu((isOpen) => !isOpen)}
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
                        onOpenBookmark(bookmark);
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
            onClick={onOrganize}
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
            onToggle={onToggle}
            onOpen={onOpen}
            onContext={(event, target, type) => {
              event.preventDefault();
              onContext({ path: target, type, x: event.clientX, y: event.clientY });
            }}
            onDragGesture={onDragGesture}
            dragTarget={dragTarget}
            activeRef={activeRowRef}
          />
        ) : (
          <div className="muted small">Loading…</div>
        )}
      </div>
    </div>
  );
}

/** Right-click menu for a tree row. */
export function TreeContextMenu({
  context,
  onClose,
  onOpen,
  onCopyPath,
  onDuplicate,
  onDelete,
}: {
  context: TreeContext;
  onClose: () => void;
  onOpen: (path: string, newTab: boolean) => void;
  onCopyPath: (path: string) => void;
  onDuplicate: (path: string) => void;
  onDelete: (path: string) => void;
}) {
  const run = (action: () => void) => () => {
    action();
    onClose();
  };
  return (
    <>
      <div className="menu-backdrop" onClick={onClose} />
      <div
        className="more-menu context-menu"
        style={{ left: context.x, top: context.y }}
      >
        {context.type === "file" && (
          <>
            <button className="more-item" onClick={run(() => onOpen(context.path, false))}>
              <Icon name="file-text" size={15} /> Open
            </button>
            <button className="more-item" onClick={run(() => onOpen(context.path, true))}>
              <Icon name="external-link" size={15} /> Open in new tab
            </button>
          </>
        )}
        <button className="more-item" onClick={run(() => onCopyPath(context.path))}>
          <Icon name="copy" size={15} /> Copy path
        </button>
        {context.type === "file" && (
          <button className="more-item" onClick={run(() => onDuplicate(context.path))}>
            <Icon name="copy" size={15} /> Duplicate note
          </button>
        )}
        <div className="more-sep" />
        <button className="more-item danger" onClick={run(() => onDelete(context.path))}>
          <Icon name="trash" size={15} /> Delete {context.type}
        </button>
      </div>
    </>
  );
}
