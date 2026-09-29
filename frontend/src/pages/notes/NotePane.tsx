// One note pane: the note's title and path, then either an editor (source or
// rich, primary pane only) or the rendered Markdown with backlinks.

import { Suspense, lazy } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins, stripFrontmatter, wikilinksToMd } from "../../markdown";
import type { VaultNote } from "../../types";
import { basename, stripExt } from "./paths";
import type { ViewMode } from "./TabBar";
import type { SelectionTranslation } from "./TranslationLayer";
import type { InlineNoteTranslation } from "./translation";

// Reading a note needs none of these; the editors load on first use (and are
// warmed in the background once the notes page is open, see preloadEditors).
const loadMarkdownEditor = () => import("../../MarkdownEditor");
const loadRichEditor = () => import("../../RichMarkdownEditor");
const MarkdownEditor = lazy(() => loadMarkdownEditor().then((m) => ({ default: m.MarkdownEditor })));
const RichMarkdownEditor = lazy(() => loadRichEditor().then((m) => ({ default: m.RichMarkdownEditor })));

export function preloadEditors() {
  void loadMarkdownEditor().catch(() => {});
  void loadRichEditor().catch(() => {});
}

const editorFallback = <div className="editor-loading muted small">Loading editor…</div>;

/** Editing state and callbacks; only the primary pane edits. */
export interface PaneEditing {
  viewMode: ViewMode;
  draft: string;
  setDraft: (value: string) => void;
  save: (value: string) => void;
  /** [[link]] / heading jump from the source editor. */
  openFromSource: (target: string) => void;
  openLinkedNote: (target: string, newTab: boolean) => void;
  openExternalUrl: (url: string) => void;
  bookmarkHeading: (heading: string) => void;
  extractHeading: (filename: string, extracted: string, updated: string) => Promise<boolean>;
  linkTargets: string[];
}

export function NotePane({
  note,
  primary,
  split,
  align,
  readingZoom,
  rendered,
  components,
  inlineTranslation,
  editing,
  translation,
  backlinksInDocument,
  onOpenBacklink,
  onClose,
  onNewSplitTab,
}: {
  note: VaultNote;
  primary: boolean;
  split: "right" | "down" | null;
  align: "left" | "center";
  readingZoom: number;
  /** Rendered Markdown of the primary note (memoised by the page). */
  rendered: string;
  /** Wikilink-aware Markdown components (primary pane only). */
  components: Components;
  inlineTranslation: InlineNoteTranslation | null;
  editing: PaneEditing;
  translation: SelectionTranslation;
  backlinksInDocument: boolean;
  onOpenBacklink: (path: string) => void;
  onClose?: () => void;
  onNewSplitTab: () => void;
}) {
  const activeInlineTranslation =
    primary && inlineTranslation?.path === note.path ? inlineTranslation : null;
  const markdown = primary
    ? activeInlineTranslation?.markdown ?? rendered
    : wikilinksToMd(stripFrontmatter(note.content));
  const { viewMode } = editing;
  return (
    <div className="pane-group">
      {!primary && split !== "right" && (
        <div className="pane-tabbar">
          <div className="pane-tab active">
            <span className="tab-label">{stripExt(basename(note.path))}</span>
            <button className="tab-close" title="Close split tab" onClick={onClose}>×</button>
          </div>
          <button className="tab-add icon-btn" title="New split tab" onClick={onNewSplitTab}>+</button>
        </div>
      )}
      <section
        className={`note-pane ${align === "center" ? "reading-centered" : "reading-left"}`}
        data-note-drop-zone={primary ? "true" : undefined}
      >
        <div className="note-page" style={{ fontSize: `${readingZoom}%` }}>
        <div className="note-pane-heading">
          <div>
            <h2 className="page-title" style={{ margin: "0 0 4px" }}>{note.name}</h2>
            {activeInlineTranslation?.title && (
              <h2 className="page-title translated-note-title">
                {activeInlineTranslation.title}
              </h2>
            )}
            <div className="small muted">{note.path}</div>
          </div>
        </div>
        {primary && viewMode === "source" ? (
          <Suspense fallback={editorFallback}>
          <MarkdownEditor
            value={editing.draft}
            onChange={editing.setDraft}
            onSave={editing.save}
            onOpenInternal={editing.openFromSource}
            onBookmarkHeading={editing.bookmarkHeading}
            onExtractHeading={editing.extractHeading}
            linkTargets={editing.linkTargets}
          />
          </Suspense>
        ) : primary && viewMode === "edit" ? (
          <Suspense fallback={editorFallback}>
          <RichMarkdownEditor
            value={editing.draft}
            onChange={editing.setDraft}
            onSave={editing.save}
            onOpenInternal={(target) => editing.openLinkedNote(target, true)}
            onOpenExternal={editing.openExternalUrl}
            linkTargets={editing.linkTargets}
          />
          </Suspense>
        ) : (
          <>
            {activeInlineTranslation?.status === "loading" && (
              <div className="note-banner">{activeInlineTranslation.progress ?? "Translating note..."}</div>
            )}
            {activeInlineTranslation?.status === "error" && (
              <div className="warn-banner">{activeInlineTranslation.error}</div>
            )}
            <div
              className="md"
              onMouseMove={translation.onHover}
              onMouseLeave={translation.clearHover}
              onKeyUp={(event) => {
                if (!(event.ctrlKey || event.metaKey)) translation.clearHover();
              }}
              onContextMenu={translation.onContextMenu}
            >
              <ReactMarkdown
                remarkPlugins={mdRemarkPlugins}
                rehypePlugins={mdRehypePlugins}
                components={{ ...mdComponents, ...(primary ? components : {}) }}
                urlTransform={(url) => url}
              >
                {markdown}
              </ReactMarkdown>
            </div>
            {primary && backlinksInDocument && (
              <div className="document-backlinks">
                <h3>Backlinks</h3>
                {note.backlinks.length ? note.backlinks.map((backlink) => (
                  <button
                    className="linked-note"
                    key={backlink.path}
                    onClick={() => onOpenBacklink(backlink.path)}
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
}
