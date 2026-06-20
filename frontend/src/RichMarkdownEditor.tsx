import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

interface RichMarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  onSave: (value: string) => void | Promise<void>;
  onOpenInternal: (target: string) => void;
  onOpenExternal: (url: string) => void;
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

marked.use({
  extensions: [
    {
      name: "wikilink",
      level: "inline",
      start: (source) => source.indexOf("[["),
      tokenizer(source) {
        const match = /^\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/.exec(source);
        if (!match) return;
        return {
          type: "wikilink",
          raw: match[0],
          target: match[1].trim(),
          label: (match[2] || match[1]).trim(),
        };
      },
      renderer(token) {
        const value = token as unknown as { target: string; label: string };
        return `<span class="rich-wikilink" data-wikilink="${escapeHtml(value.target)}">${escapeHtml(value.label)}</span>`;
      },
    },
    {
      name: "highlight",
      level: "inline",
      start: (source) => source.indexOf("=="),
      tokenizer(source) {
        const match = /^==([^=\n]+)==/.exec(source);
        if (!match) return;
        return { type: "highlight", raw: match[0], text: match[1] };
      },
      renderer(token) {
        const value = token as unknown as { text: string };
        return `<mark>${escapeHtml(value.text)}</mark>`;
      },
    },
  ],
});

function splitFrontmatter(raw: string) {
  const match = /^(---\r?\n[\s\S]*?\r?\n---\r?\n)([\s\S]*)$/.exec(raw);
  return match
    ? { frontmatter: match[1], body: match[2] }
    : { frontmatter: "", body: raw };
}

function safeHtml(markdown: string) {
  const parsed = marked.parse(markdown, { async: false }) as string;
  const document = new DOMParser().parseFromString(parsed, "text/html");
  document.querySelectorAll("script, style, iframe, object, embed").forEach((node) => node.remove());
  document.querySelectorAll("*").forEach((node) => {
    for (const attribute of [...node.attributes]) {
      if (
        attribute.name.toLowerCase().startsWith("on") ||
        /^(?:javascript|data):/i.test(attribute.value.trim())
      ) {
        node.removeAttribute(attribute.name);
      }
    }
  });
  return document.body.innerHTML;
}

const turndown = new TurndownService({
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  emDelimiter: "*",
  strongDelimiter: "**",
});
turndown.use(gfm);

turndown.addRule("highlight", {
  filter: ["mark"],
  replacement: (content) => `==${content}==`,
});
turndown.addRule("wikilink", {
  filter: (node) => node instanceof HTMLElement && node.hasAttribute("data-wikilink"),
  replacement: (content, node) => {
    const target = (node as HTMLElement).getAttribute("data-wikilink") || content;
    return content === target ? `[[${target}]]` : `[[${target}|${content}]]`;
  },
});

export function RichMarkdownEditor({
  value,
  onChange,
  onSave,
  onOpenInternal,
  onOpenExternal,
}: RichMarkdownEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null);
  const frontmatterRef = useRef("");
  const lastValueRef = useRef("");
  const savedRangeRef = useRef<Range | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const [menu, setMenu] = useState<{
    x: number;
    y: number;
    submenu: "format" | "paragraph" | "insert" | null;
    hasSelection: boolean;
  } | null>(null);

  useEffect(() => {
    if (!editorRef.current || value === lastValueRef.current) return;
    const { frontmatter, body } = splitFrontmatter(value);
    frontmatterRef.current = frontmatter;
    editorRef.current.innerHTML = safeHtml(body);
    lastValueRef.current = value;
  }, [value]);

  const sync = () => {
    if (!editorRef.current) return;
    const body = turndown.turndown(editorRef.current.innerHTML).trim();
    const trailingNewline = valueRef.current.endsWith("\n") ? "\n" : "";
    const next = `${frontmatterRef.current}${body}${trailingNewline}`;
    lastValueRef.current = next;
    onChange(next);
  };

  const restoreSelection = () => {
    editorRef.current?.focus();
    const selection = window.getSelection();
    if (selection && savedRangeRef.current) {
      selection.removeAllRanges();
      selection.addRange(savedRangeRef.current);
    }
  };

  const closeMenu = () => {
    setMenu(null);
    savedRangeRef.current = null;
  };

  const command = (name: string, value?: string) => {
    restoreSelection();
    document.execCommand(name, false, value);
    sync();
    closeMenu();
  };

  const insertHtml = (html: string) => {
    restoreSelection();
    document.execCommand("insertHTML", false, html);
    sync();
    closeMenu();
  };

  const wrapElement = (tag: "code" | "mark") => {
    restoreSelection();
    const selection = window.getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0);
    const element = document.createElement(tag);
    if (range.collapsed) {
      element.textContent = tag === "code" ? "code" : "highlight";
    } else {
      element.appendChild(range.extractContents());
    }
    range.insertNode(element);
    range.selectNodeContents(element);
    selection.removeAllRanges();
    selection.addRange(range);
    sync();
    closeMenu();
  };

  const selectedText = () => {
    restoreSelection();
    return window.getSelection()?.toString() || "";
  };

  const addInternalLink = () => {
    const selection = selectedText();
    const target = window.prompt(
      "Note/material name or vault-relative path:",
      selection,
    );
    if (!target) return;
    const label = selection || window.prompt("Link text:", target) || target;
    insertHtml(
      `<span class="rich-wikilink" data-wikilink="${escapeHtml(target.trim())}">${escapeHtml(label)}</span>`,
    );
  };

  const addExternalLink = () => {
    const selection = selectedText();
    const url = window.prompt("External URL:", "https://");
    if (!url) return;
    const label = selection || window.prompt("Link text:", url) || url;
    insertHtml(`<a href="${escapeHtml(url)}">${escapeHtml(label)}</a>`);
  };

  const clipboardSelection = async (cut: boolean) => {
    const text = selectedText();
    if (!text) return;
    await navigator.clipboard.writeText(text);
    if (cut) {
      restoreSelection();
      document.execCommand("delete");
      sync();
    }
    closeMenu();
  };

  const paste = async () => {
    const text = await navigator.clipboard.readText();
    insertHtml(escapeHtml(text).replace(/\r?\n/g, "<br>"));
  };

  const selectAll = () => {
    const editor = editorRef.current;
    if (!editor) return;
    const range = document.createRange();
    range.selectNodeContents(editor);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    savedRangeRef.current = range.cloneRange();
    setMenu((current) => current && { ...current, hasSelection: true });
  };

  const openContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault();
    const editor = editorRef.current;
    if (!editor) return;
    const selection = window.getSelection();
    if (!selection?.rangeCount || selection.isCollapsed) {
      const caretFromPoint = (
        document as Document & {
          caretRangeFromPoint?: (x: number, y: number) => Range | null;
        }
      ).caretRangeFromPoint?.(event.clientX, event.clientY);
      if (caretFromPoint && editor.contains(caretFromPoint.startContainer)) {
        selection?.removeAllRanges();
        selection?.addRange(caretFromPoint);
      }
    }
    const range = selection?.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
    savedRangeRef.current = range;
    setMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 455)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 390)),
      submenu: null,
      hasSelection: !!selection && !selection.isCollapsed,
    });
  };

  return (
    <div
      className="rich-editor-shell"
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
          event.preventDefault();
          void onSave(valueRef.current);
        }
      }}
    >
      <div className="rich-editor-toolbar" aria-label="Formatting toolbar">
        <button type="button" title="Bold" onMouseDown={(event) => event.preventDefault()} onClick={() => command("bold")}><strong>B</strong></button>
        <button type="button" title="Italic" onMouseDown={(event) => event.preventDefault()} onClick={() => command("italic")}><em>I</em></button>
        <button type="button" title="Heading 1" onMouseDown={(event) => event.preventDefault()} onClick={() => command("formatBlock", "h1")}>H1</button>
        <button type="button" title="Heading 2" onMouseDown={(event) => event.preventDefault()} onClick={() => command("formatBlock", "h2")}>H2</button>
        <button type="button" title="Normal paragraph" onMouseDown={(event) => event.preventDefault()} onClick={() => command("formatBlock", "p")}>¶</button>
        <button type="button" title="Bullet list" onMouseDown={(event) => event.preventDefault()} onClick={() => command("insertUnorderedList")}>• List</button>
        <button type="button" title="Numbered list" onMouseDown={(event) => event.preventDefault()} onClick={() => command("insertOrderedList")}>1. List</button>
        <button type="button" title="Quote" onMouseDown={(event) => event.preventDefault()} onClick={() => command("formatBlock", "blockquote")}>Quote</button>
      </div>
      <div
        ref={editorRef}
        className="rich-editor md"
        contentEditable
        suppressContentEditableWarning
        spellCheck
        onInput={sync}
        onContextMenu={openContextMenu}
        onClick={(event) => {
          const element = event.target as HTMLElement;
          const internal = element.closest<HTMLElement>("[data-wikilink]");
          if (internal) {
            event.preventDefault();
            onOpenInternal(internal.dataset.wikilink || internal.textContent || "");
            return;
          }
          const anchor = element.closest<HTMLAnchorElement>("a[href]");
          if (anchor) {
            event.preventDefault();
            const href = anchor.getAttribute("href") || "";
            if (/^(?:https?:|mailto:)/i.test(href)) onOpenExternal(href);
            else onOpenInternal(href);
          }
        }}
      />
      {menu && (
        <>
          <div className="editor-menu-backdrop" onMouseDown={closeMenu} />
          <div
            className="editor-context-menu rich-editor-context-menu"
            style={{ left: menu.x, top: menu.y }}
          >
            <button className="editor-menu-item" onClick={addInternalLink}>
              Add link
            </button>
            <button className="editor-menu-item" onClick={addExternalLink}>
              Add external link
            </button>
            <div className="more-sep" />
            {(["format", "paragraph", "insert"] as const).map((submenu) => (
              <button
                className="editor-menu-item"
                key={submenu}
                onMouseEnter={() =>
                  setMenu((current) => current && { ...current, submenu })
                }
                onClick={() =>
                  setMenu((current) => current && { ...current, submenu })
                }
              >
                <span>{submenu[0].toUpperCase() + submenu.slice(1)}</span>
                <span className="menu-arrow">›</span>
              </button>
            ))}
            <div className="more-sep" />
            <button
              className="editor-menu-item"
              disabled={!menu.hasSelection}
              onClick={() => void clipboardSelection(true)}
            >
              Cut
            </button>
            <button
              className="editor-menu-item"
              disabled={!menu.hasSelection}
              onClick={() => void clipboardSelection(false)}
            >
              Copy
            </button>
            <button className="editor-menu-item" onClick={() => void paste()}>
              Paste
            </button>
            <button className="editor-menu-item" onClick={() => void paste()}>
              Paste as plain text
            </button>
            <button className="editor-menu-item" onClick={selectAll}>
              Select all
            </button>

            {menu.submenu === "format" && (
              <div className="editor-context-submenu" style={{ top: 69 }}>
                <button className="editor-menu-item" onClick={() => command("bold")}>Bold</button>
                <button className="editor-menu-item" onClick={() => command("italic")}>Italic</button>
                <button className="editor-menu-item" onClick={() => command("strikeThrough")}>Strikethrough</button>
                <button className="editor-menu-item" onClick={() => wrapElement("code")}>Inline code</button>
                <button className="editor-menu-item" onClick={() => wrapElement("mark")}>Highlight</button>
              </div>
            )}
            {menu.submenu === "paragraph" && (
              <div className="editor-context-submenu" style={{ top: 101 }}>
                <button className="editor-menu-item" onClick={() => command("formatBlock", "p")}>Normal text</button>
                {[1, 2, 3, 4, 5, 6].map((level) => (
                  <button
                    className="editor-menu-item"
                    key={level}
                    onClick={() => command("formatBlock", `h${level}`)}
                  >
                    Heading {level}
                  </button>
                ))}
                <div className="more-sep" />
                <button className="editor-menu-item" onClick={() => command("formatBlock", "blockquote")}>Quote</button>
                <button className="editor-menu-item" onClick={() => command("insertUnorderedList")}>Bullet list</button>
                <button className="editor-menu-item" onClick={() => command("insertOrderedList")}>Numbered list</button>
              </div>
            )}
            {menu.submenu === "insert" && (
              <div className="editor-context-submenu" style={{ top: 133 }}>
                <button className="editor-menu-item" onClick={() => insertHtml("<pre><code>code</code></pre>")}>Code block</button>
                <button className="editor-menu-item" onClick={() => insertHtml("<blockquote><strong>Note</strong><br>Callout text</blockquote>")}>Callout</button>
                <button className="editor-menu-item" onClick={() => insertHtml("<table><thead><tr><th>Column 1</th><th>Column 2</th></tr></thead><tbody><tr><td><br></td><td><br></td></tr></tbody></table>")}>Table</button>
                <button className="editor-menu-item" onClick={() => insertHtml("<hr>")}>Horizontal rule</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
