// The tab bar above the note: open tabs, the note's action buttons (save,
// translate, AI format, alignment, text size, source/edit/read view), the ⋮
// "More options" menu, and the tab strip of a right-hand split.

import { useState } from "react";
import { Icon } from "../../icons";
import type { VaultNote } from "../../types";
import { basename, clamp, isNewTab, stripExt } from "./paths";

export type ViewMode = "source" | "edit" | "read";

const TEXT_SIZES = [
  [90, "Compact"],
  [100, "Normal"],
  [115, "Large"],
  [130, "Extra large"],
  [150, "Presentation"],
] as const;

/** What the ⋮ menu and the action buttons can do to the active note. */
export interface NoteActions {
  save: () => void;
  translate: () => void;
  format: () => void;
  toggleAlign: () => void;
  setZoom: (size: number) => void;
  changeView: (mode: ViewMode) => void;
  toggleBacklinksInDocument: () => void;
  reviewMentions: () => void;
  split: (direction: "right" | "down", target?: string) => void;
  openNewWindow: () => void;
  rename: () => void;
  toggleBookmark: () => void;
  merge: () => void;
  addProperty: () => void;
  exportPdf: () => void;
  find: (mode: "find" | "replace") => void;
  copyPath: () => void;
  versionHistory: () => void;
  localGraph: () => void;
  openExternal: () => void;
  revealInSystem: () => void;
  revealInTree: () => void;
  remove: () => void;
}

export function TabBar({
  tabs,
  active,
  onSelect,
  onClose,
  onNewTab,
  note,
  actionable,
  dirty,
  saving,
  translating,
  formatting,
  align,
  readingZoom,
  viewMode,
  backlinksInDocument,
  bookmarked,
  actions,
  split,
  splitNote,
  onCloseSplit,
  onNewSplitTab,
}: {
  tabs: string[];
  active: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onNewTab: () => void;
  note: VaultNote | null;
  /** A real note is open in the active tab (not an empty new tab). */
  actionable: boolean;
  dirty: boolean;
  saving: boolean;
  translating: boolean;
  formatting: boolean;
  align: "left" | "center";
  readingZoom: number;
  viewMode: ViewMode;
  backlinksInDocument: boolean;
  bookmarked: boolean;
  actions: NoteActions;
  split: "right" | "down" | null;
  splitNote: VaultNote | null;
  onCloseSplit: () => void;
  onNewSplitTab: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [linkedMenu, setLinkedMenu] = useState(false);
  const [textSizeMenu, setTextSizeMenu] = useState(false);
  const [textSizePosition, setTextSizePosition] = useState({ top: 0, left: 0 });

  /** Close the ⋮ menu, then run the action. */
  const fromMenu = (action: () => void) => () => {
    setMenuOpen(false);
    action();
  };
  const openSplit = (direction: "right" | "down", target?: string) => {
    actions.split(direction, target);
    setMenuOpen(false);
  };

  return (
    <div className={`tabbar ${split === "right" ? "has-right-split" : ""}`}>
      <div className="primary-tab-strip">
      {tabs.map((p) => (
        <div
          key={p}
          className={`tab ${p === active ? "active" : ""} ${isNewTab(p) ? "newtab" : ""}`}
          onClick={() => onSelect(p)}
          onMouseDown={(e) => {
            if (e.button === 1) {
              e.preventDefault();
              onClose(p);
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
              onClose(p);
            }}
          >
            ✕
          </span>
        </div>
      ))}
      <button className="tab-add icon-btn" title="Open new tab" onClick={onNewTab}>
        +
      </button>

      {actionable && (
        <div className="tab-actions">
          {dirty && (
            <button
              className="icon-btn"
              style={{ color: "var(--accent)" }}
              title="Save"
              onClick={actions.save}
              disabled={saving}
            >
              Save
            </button>
          )}
          <button
            className="icon-btn"
            title="Create translated Chinese note"
            onClick={actions.translate}
            disabled={!note || translating}
          >
            <Icon name="languages" size={17} />
          </button>
          <button
            className="icon-btn"
            title="AI format document"
            onClick={actions.format}
            disabled={formatting}
          >
            <Icon name="sparkles" size={17} />
          </button>
          <button
            className="icon-btn"
            title={align === "center" ? "Align left" : "Align center"}
            onClick={actions.toggleAlign}
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
                  {TEXT_SIZES.map(([size, label]) => (
                    <button
                      className={`text-size-option ${readingZoom === size ? "selected" : ""}`}
                      key={size}
                      onClick={() => {
                        actions.setZoom(size);
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
            onClick={() => actions.changeView("source")}
          >
            <Icon name="code" size={17} />
          </button>
          <button
            className={`icon-btn ${viewMode === "edit" ? "active" : ""}`}
            title={viewMode === "edit" ? "Return to reading view" : "Edit view"}
            onClick={() => actions.changeView(viewMode === "edit" ? "read" : "edit")}
          >
            <Icon name="pencil" size={17} />
          </button>
          <button
            className={`icon-btn ${viewMode === "read" ? "active" : ""}`}
            title="Reading view"
            onClick={() => actions.changeView("read")}
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
                  <button className="more-item" onClick={fromMenu(actions.toggleBacklinksInDocument)}>
                    <Icon name="graph" size={15} /> Backlinks in document
                    {backlinksInDocument && <span className="menu-check">✓</span>}
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.reviewMentions)}>
                    <Icon name="search" size={15} /> Search unlinked mentions
                  </button>
                  <button className="more-item" onClick={fromMenu(() => actions.changeView("read"))}>
                    <Icon name="book" size={15} /> Reading view
                  </button>
                  <div className="more-sep" />
                  <button className="more-item" onClick={() => openSplit("right")}>
                    <Icon name="panel-right" size={15} /> Split right
                  </button>
                  <button className="more-item" onClick={() => openSplit("down")}>
                    <Icon name="panel-left" size={15} /> Split down
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.openNewWindow)}>
                    <Icon name="external-link" size={15} /> Open in new window
                  </button>
                  <div className="more-sep" />
                  <button className="more-item" onClick={fromMenu(actions.rename)}>
                    <Icon name="pencil" size={15} /> Rename…
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.toggleBookmark)}>
                    <Icon name="book" size={15} /> {bookmarked ? "Remove bookmark" : "Bookmark…"}
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.merge)}>
                    <Icon name="layers" size={15} /> Merge entire file with…
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.addProperty)}>
                    <Icon name="file-plus" size={15} /> Add file property
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.exportPdf)}>
                    <Icon name="download" size={15} /> Export to PDF…
                  </button>
                  <div className="more-sep" />
                  <button className="more-item" onClick={fromMenu(() => actions.find("find"))}>
                    <Icon name="search" size={15} /> Find…
                  </button>
                  <button className="more-item" onClick={fromMenu(() => actions.find("replace"))}>
                    <Icon name="pencil" size={15} /> Replace…
                  </button>
                  <div className="more-sep" />
                  <button className="more-item" onClick={fromMenu(actions.copyPath)}>
                    <Icon name="copy" size={15} /> Copy path
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.versionHistory)}>
                    <Icon name="reveal" size={15} /> Open version history
                  </button>
                  <button className="more-item" onClick={() => setLinkedMenu((value) => !value)}>
                    <Icon name="graph" size={15} /> Open linked view
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.localGraph)}>
                    <Icon name="graph" size={15} /> Local graph
                  </button>
                  {linkedMenu && (
                    <div className="linked-view-menu">
                      {[...(note?.links ?? []).filter((item) => item.path), ...(note?.backlinks ?? [])]
                        // A note that links here and is linked from here is listed once.
                        .filter((item, index, all) => all.findIndex((other) => other.path === item.path) === index)
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
                  <button className="more-item" onClick={fromMenu(actions.openExternal)}>
                    <Icon name="external-link" size={15} /> Open in default app
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.revealInSystem)}>
                    <Icon name="reveal" size={15} /> Show in system explorer
                  </button>
                  <button className="more-item" onClick={fromMenu(actions.revealInTree)}>
                    <Icon name="folder" size={15} /> Reveal file in navigation
                  </button>
                  <div className="more-sep" />
                  <button className="more-item danger" onClick={fromMenu(actions.remove)}>
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
                onClick={onCloseSplit}
              >×</button>
            </div>
          ) : (
            <div className="tab newtab active"><span className="tab-label">New tab</span></div>
          )}
          <button
            className="tab-add icon-btn"
            title="New split tab"
            onClick={onNewSplitTab}
          >+</button>
        </div>
      )}
    </div>
  );
}
