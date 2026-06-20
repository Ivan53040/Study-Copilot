import { useMemo, useRef, useState } from "react";
import CodeMirror, { type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { EditorSelection, EditorState } from "@codemirror/state";
import { keymap, EditorView } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";

interface HeadingContext {
  level: number;
  text: string;
  slug: string;
  lineFrom: number;
  sectionTo: number;
  content: string;
}

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  onSave: (value: string) => void | Promise<void>;
  onOpenInternal: (target: string) => void;
  onBookmarkHeading: (heading: string) => void;
  onExtractHeading: (
    filename: string,
    extractedContent: string,
    updatedDocument: string,
  ) => Promise<boolean>;
}

type Submenu = "format" | "paragraph" | "insert" | null;

const headingSlug = (text: string) =>
  text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/^-+|-+$/g, "");

export function MarkdownEditor({
  value,
  onChange,
  onSave,
  onOpenInternal,
  onBookmarkHeading,
  onExtractHeading,
}: MarkdownEditorProps) {
  const editorRef = useRef<ReactCodeMirrorRef>(null);
  const saveRef = useRef(onSave);
  const openInternalRef = useRef(onOpenInternal);
  saveRef.current = onSave;
  openInternalRef.current = onOpenInternal;
  const [menu, setMenu] = useState<{
    x: number;
    y: number;
    submenu: Submenu;
    hasSelection: boolean;
    heading: HeadingContext | null;
  } | null>(null);

  const extensions = useMemo(
    () => [
      history(),
      markdown({ base: markdownLanguage }),
      EditorView.lineWrapping,
      EditorState.tabSize.of(2),
      keymap.of([
        ...defaultKeymap,
        ...historyKeymap,
        indentWithTab,
        {
          key: "Mod-s",
          preventDefault: true,
          run: (view) => {
            void saveRef.current(view.state.doc.toString());
            return true;
          },
        },
      ]),
      syntaxHighlighting(
        HighlightStyle.define([
          { tag: tags.heading1, color: "var(--text)", fontSize: "1.55em", fontWeight: "700" },
          { tag: tags.heading2, color: "var(--text)", fontSize: "1.35em", fontWeight: "700" },
          { tag: tags.heading3, color: "var(--text)", fontSize: "1.18em", fontWeight: "650" },
          { tag: tags.strong, color: "var(--text)", fontWeight: "700" },
          { tag: tags.emphasis, color: "var(--text)", fontStyle: "italic" },
          { tag: tags.link, color: "var(--accent)", textDecoration: "underline" },
          { tag: tags.url, color: "var(--accent)" },
          { tag: tags.monospace, color: "var(--warn)" },
          { tag: tags.quote, color: "var(--muted)", fontStyle: "italic" },
          { tag: tags.meta, color: "var(--muted)" },
          { tag: tags.processingInstruction, color: "var(--muted)" },
        ]),
      ),
      EditorView.theme({
        "&": {
          height: "100%",
          backgroundColor: "transparent",
          color: "var(--text)",
          fontSize: "calc(var(--base-font-size, 14px) + 1px)",
        },
        ".cm-scroller": {
          fontFamily: "var(--font, Inter, system-ui, sans-serif)",
          lineHeight: "1.65",
          overflow: "auto",
        },
        ".cm-content": { padding: "8px 0 80px", caretColor: "var(--accent)" },
        ".cm-line": { padding: "0 4px" },
        ".cm-gutters": {
          backgroundColor: "transparent",
          color: "var(--muted)",
          border: "none",
          paddingRight: "8px",
        },
        ".cm-activeLine, .cm-activeLineGutter": {
          backgroundColor: "color-mix(in srgb, var(--accent) 7%, transparent)",
        },
        ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
          backgroundColor: "color-mix(in srgb, var(--accent) 28%, transparent) !important",
        },
        "&.cm-focused": { outline: "none" },
      }),
      EditorView.domEventHandlers({
        mousedown(event, view) {
          if (!(event.ctrlKey || event.metaKey) || event.button !== 0) return false;
          const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
          if (pos === null) return false;
          const line = view.state.doc.lineAt(pos);
          const offset = pos - line.from;
          const patterns = [
            /\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]+)?\]\]/g,
            /\[([^\]]+)\]\((?!https?:|mailto:)([^)]+)\)/g,
          ];
          for (const pattern of patterns) {
            let match: RegExpExecArray | null;
            while ((match = pattern.exec(line.text))) {
              if (offset >= match.index && offset <= match.index + match[0].length) {
                const target = pattern.source.startsWith("\\[\\[") ? match[1] : match[2];
                openInternalRef.current(target.trim());
                event.preventDefault();
                return true;
              }
            }
          }
          return false;
        },
      }),
    ],
    [],
  );

  const getView = () => editorRef.current?.view ?? null;

  const selectionInfo = () => {
    const view = getView();
    if (!view) return null;
    const range = view.state.selection.main;
    return {
      view,
      from: range.from,
      to: range.to,
      text: view.state.sliceDoc(range.from, range.to),
    };
  };

  const replaceRange = (from: number, to: number, insert: string, select?: [number, number]) => {
    const view = getView();
    if (!view) return;
    const anchor = select ? from + select[0] : from + insert.length;
    const head = select ? from + select[1] : anchor;
    view.dispatch({
      changes: { from, to, insert },
      selection: EditorSelection.single(anchor, head),
    });
    view.focus();
    setMenu(null);
  };

  const wrapSelection = (before: string, after = before, placeholder = "text") => {
    const selection = selectionInfo();
    if (!selection) return;
    const body = selection.text || placeholder;
    replaceRange(
      selection.from,
      selection.to,
      `${before}${body}${after}`,
      selection.text
        ? undefined
        : [before.length, before.length + placeholder.length],
    );
  };

  const transformLines = (transform: (line: string, index: number) => string) => {
    const selection = selectionInfo();
    if (!selection) return;
    const startLine = selection.view.state.doc.lineAt(selection.from);
    const endLine = selection.view.state.doc.lineAt(selection.to);
    const source = selection.view.state.sliceDoc(startLine.from, endLine.to);
    replaceRange(
      startLine.from,
      endLine.to,
      source.split("\n").map(transform).join("\n"),
    );
  };

  const setHeading = (level: number) =>
    transformLines((line) => `${level ? `${"#".repeat(level)} ` : ""}${line.replace(/^#{1,6}\s+/, "")}`);

  const setLinePrefix = (prefix: string) =>
    transformLines((line, index) => `${prefix.replace("{n}", String(index + 1))}${line.replace(/^(?:[-*+] |\d+\. |> |-\s+\[[ xX]\]\s+)/, "")}`);

  const insertBlock = (text: string) => {
    const selection = selectionInfo();
    if (!selection) return;
    const insert = selection.text ? text.replace("{selection}", selection.text) : text.replace("{selection}", "");
    replaceRange(selection.from, selection.to, insert);
  };

  const addInternalLink = () => {
    const selection = selectionInfo();
    if (!selection) return;
    const target = window.prompt("Note name or vault-relative path:", selection.text);
    if (!target) return;
    const insert = selection.text && selection.text !== target
      ? `[[${target}|${selection.text}]]`
      : `[[${target}]]`;
    replaceRange(selection.from, selection.to, insert);
  };

  const addExternalLink = () => {
    const selection = selectionInfo();
    if (!selection) return;
    const url = window.prompt("External URL:", "https://");
    if (!url) return;
    const label = selection.text || window.prompt("Link text:", url) || url;
    replaceRange(selection.from, selection.to, `[${label}](${url})`);
  };

  const copySelection = async (cut: boolean) => {
    const selection = selectionInfo();
    if (!selection?.text) return;
    await navigator.clipboard.writeText(selection.text);
    if (cut) replaceRange(selection.from, selection.to, "");
    else setMenu(null);
  };

  const pasteText = async () => {
    const selection = selectionInfo();
    if (!selection) return;
    const text = await navigator.clipboard.readText();
    replaceRange(selection.from, selection.to, text);
  };

  const selectAll = () => {
    const view = getView();
    if (!view) return;
    view.dispatch({ selection: EditorSelection.single(0, view.state.doc.length) });
    view.focus();
    setMenu(null);
  };

  const headingAt = (position: number): HeadingContext | null => {
    const view = getView();
    if (!view) return null;
    const line = view.state.doc.lineAt(position);
    const match = /^(#{1,6})\s+(.+?)\s*$/.exec(line.text);
    if (!match) return null;
    const level = match[1].length;
    let sectionTo = view.state.doc.length;
    for (let number = line.number + 1; number <= view.state.doc.lines; number++) {
      const next = view.state.doc.line(number);
      const nextHeading = /^(#{1,6})\s+/.exec(next.text);
      if (nextHeading && nextHeading[1].length <= level) {
        sectionTo = Math.max(line.to, next.from - 1);
        break;
      }
    }
    return {
      level,
      text: match[2],
      slug: headingSlug(match[2]),
      lineFrom: line.from,
      sectionTo,
      content: view.state.sliceDoc(line.from, sectionTo),
    };
  };

  const renameHeading = () => {
    if (!menu?.heading) return;
    const name = window.prompt("Rename heading:", menu.heading.text);
    if (!name) return;
    const view = getView();
    if (!view) return;
    const line = view.state.doc.lineAt(menu.heading.lineFrom);
    replaceRange(line.from, line.to, `${"#".repeat(menu.heading.level)} ${name}`);
  };

  const extractHeading = async () => {
    if (!menu?.heading) return;
    const filename = window.prompt("Extract heading to note:", menu.heading.text);
    if (!filename) return;
    const view = getView();
    if (!view) return;
    const target = filename.replace(/\.(md|markdown|txt)$/i, "");
    const updated =
      view.state.sliceDoc(0, menu.heading.lineFrom) +
      `[[${target}]]` +
      view.state.sliceDoc(menu.heading.sectionTo);
    const saved = await onExtractHeading(filename, menu.heading.content, updated);
    if (saved) setMenu(null);
  };

  const openContextMenu = (event: React.MouseEvent) => {
    event.preventDefault();
    const view = getView();
    if (!view) return;
    const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
    if (pos === null) return;
    const current = view.state.selection.main;
    if (pos < current.from || pos > current.to) {
      view.dispatch({ selection: EditorSelection.cursor(pos) });
    }
    const selection = view.state.selection.main;
    setMenu({
      x: Math.min(event.clientX, window.innerWidth - 230),
      y: Math.min(event.clientY, window.innerHeight - 430),
      submenu: null,
      hasSelection: !selection.empty,
      heading: headingAt(pos),
    });
  };

  const submenuButton = (label: string, submenu: Exclude<Submenu, null>) => (
    <button
      className="editor-menu-item"
      onMouseEnter={() => setMenu((current) => current && ({ ...current, submenu }))}
      onClick={() => setMenu((current) => current && ({ ...current, submenu }))}
    >
      <span>{label}</span><span className="menu-arrow">›</span>
    </button>
  );

  return (
    <div className="markdown-editor-shell" onContextMenu={openContextMenu}>
      <CodeMirror
        ref={editorRef}
        value={value}
        height="100%"
        extensions={extensions}
        onChange={onChange}
        basicSetup={{
          lineNumbers: false,
          foldGutter: true,
          highlightActiveLine: true,
          highlightSelectionMatches: true,
          bracketMatching: true,
          closeBrackets: true,
          autocompletion: true,
          searchKeymap: true,
        }}
      />
      {menu && (
        <>
          <div className="editor-menu-backdrop" onMouseDown={() => setMenu(null)} />
          <div className="editor-context-menu" style={{ left: menu.x, top: menu.y }}>
            <button className="editor-menu-item" onClick={addInternalLink}>Add link</button>
            <button className="editor-menu-item" onClick={addExternalLink}>Add external link</button>
            <div className="more-sep" />
            {submenuButton("Format", "format")}
            {submenuButton("Paragraph", "paragraph")}
            {submenuButton("Insert", "insert")}
            <div className="more-sep" />
            <button className="editor-menu-item" disabled={!menu.hasSelection} onClick={() => void copySelection(true)}>Cut</button>
            <button className="editor-menu-item" disabled={!menu.hasSelection} onClick={() => void copySelection(false)}>Copy</button>
            <button className="editor-menu-item" onClick={() => void pasteText()}>Paste</button>
            <button className="editor-menu-item" onClick={() => void pasteText()}>Paste as plain text</button>
            <button className="editor-menu-item" onClick={selectAll}>Select all</button>
            {menu.heading && (
              <>
                <div className="more-sep" />
                <button className="editor-menu-item" onClick={renameHeading}>Rename this heading…</button>
                <button className="editor-menu-item" onClick={() => {
                  onBookmarkHeading(menu.heading!.slug);
                  setMenu(null);
                }}>Bookmark this heading…</button>
                <button className="editor-menu-item" onClick={() => void extractHeading()}>Extract this heading…</button>
              </>
            )}
            {menu.submenu === "format" && (
              <div className="editor-context-submenu">
                <button className="editor-menu-item" onClick={() => wrapSelection("**")}>Bold</button>
                <button className="editor-menu-item" onClick={() => wrapSelection("*")}>Italic</button>
                <button className="editor-menu-item" onClick={() => wrapSelection("~~")}>Strikethrough</button>
                <button className="editor-menu-item" onClick={() => wrapSelection("`")}>Inline code</button>
                <button className="editor-menu-item" onClick={() => wrapSelection("==")}>Highlight</button>
              </div>
            )}
            {menu.submenu === "paragraph" && (
              <div className="editor-context-submenu">
                <button className="editor-menu-item" onClick={() => setHeading(0)}>Normal text</button>
                {[1, 2, 3, 4, 5, 6].map((level) => (
                  <button className="editor-menu-item" key={level} onClick={() => setHeading(level)}>
                    Heading {level}
                  </button>
                ))}
                <div className="more-sep" />
                <button className="editor-menu-item" onClick={() => setLinePrefix("> ")}>Quote</button>
                <button className="editor-menu-item" onClick={() => setLinePrefix("- ")}>Bullet list</button>
                <button className="editor-menu-item" onClick={() => setLinePrefix("{n}. ")}>Numbered list</button>
                <button className="editor-menu-item" onClick={() => setLinePrefix("- [ ] ")}>Task list</button>
              </div>
            )}
            {menu.submenu === "insert" && (
              <div className="editor-context-submenu">
                <button className="editor-menu-item" onClick={() => insertBlock("```\n{selection}\n```")}>Code block</button>
                <button className="editor-menu-item" onClick={() => insertBlock("> [!NOTE]\n> {selection}")}>Callout</button>
                <button className="editor-menu-item" onClick={() => insertBlock("| Column 1 | Column 2 |\n| --- | --- |\n|  |  |")}>Table</button>
                <button className="editor-menu-item" onClick={() => insertBlock("\n---\n")}>Horizontal rule</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
