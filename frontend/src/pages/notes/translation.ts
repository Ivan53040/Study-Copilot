// Translation helpers for reading view: Ctrl/⌘-hover a word for a tooltip,
// right-click a selection for a popup. Pure functions and DOM lookups only;
// the state lives in useSelectionTranslation (TranslationLayer.tsx).

import type React from "react";

export const TRANSLATION_MAX_CHARS = 4000;
const NOTE_TRANSLATION_CACHE_PREFIX = "study-copilot-note-translation:";

export type TranslationStatus = "loading" | "ready" | "error";
export type TranslationBubble = {
  text: string;
  translation: string | null;
  status: TranslationStatus;
  error?: string;
  x: number;
  y: number;
};
export type TranslationMenu = { text: string; x: number; y: number };
export type InlineNoteTranslation = {
  path: string;
  title: string | null;
  markdown: string;
  status: TranslationStatus;
  progress?: string;
  error?: string;
};
export type MarkdownBlock = {
  markdown: string;
  text: string;
  kind: "heading" | "text" | "skip";
  headingPrefix?: string;
};
export type MarkdownChunk = {
  kind: "translate" | "skip";
  markdown: string;
  text: string;
};

export function normalizeTranslationText(text: string): string {
  return text.replace(/\s+\n/g, "\n").replace(/\n\s+/g, "\n").replace(/[ \t]+/g, " ").trim();
}

export function isTranslatableText(text: string, maxChars = TRANSLATION_MAX_CHARS): boolean {
  const cleaned = normalizeTranslationText(text);
  return cleaned.length > 1 && cleaned.length <= maxChars && /[A-Za-z]/.test(cleaned);
}

function isIgnoredTranslationTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    !!target.closest("a, code, pre, button, input, textarea, select, .wikilink")
  );
}

function textNodeAtPoint(x: number, y: number): { node: Text; offset: number } | null {
  const doc = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  };
  const range = doc.caretRangeFromPoint?.(x, y);
  if (range?.startContainer.nodeType === Node.TEXT_NODE) {
    return { node: range.startContainer as Text, offset: range.startOffset };
  }
  const position = doc.caretPositionFromPoint?.(x, y);
  if (position?.offsetNode.nodeType === Node.TEXT_NODE) {
    return { node: position.offsetNode as Text, offset: position.offset };
  }
  return null;
}

/** The English word under the pointer inside `container`, if any. */
export function wordAtPoint(event: React.MouseEvent, container: HTMLElement): string | null {
  if (isIgnoredTranslationTarget(event.target)) return null;
  const hit = textNodeAtPoint(event.clientX, event.clientY);
  if (!hit || !container.contains(hit.node.parentElement)) return null;
  const text = hit.node.textContent ?? "";
  let start = Math.min(hit.offset, text.length);
  let end = start;
  const isWord = (char: string) => /[A-Za-z'-]/.test(char);
  while (start > 0 && isWord(text[start - 1])) start--;
  while (end < text.length && isWord(text[end])) end++;
  const word = normalizeTranslationText(text.slice(start, end).replace(/^['-]+|['-]+$/g, ""));
  return /^[A-Za-z][A-Za-z'-]*$/.test(word) && word.length > 1 ? word : null;
}

/** The selected text, when the whole selection is inside `container`. */
export function selectedTextIn(container: HTMLElement): string | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  const start = range.startContainer.parentElement;
  const end = range.endContainer.parentElement;
  if (!start || !end || !container.contains(start) || !container.contains(end)) return null;
  const text = normalizeTranslationText(selection.toString());
  return isTranslatableText(text) ? text : null;
}

// --- Whole-note (bilingual) translation helpers. Not wired into the UI at the
// moment (whole notes are translated into a new file by the backend); kept for
// an in-place bilingual view.

export function splitTranslationText(text: string, maxChars = 3600): string[] {
  const chunks: string[] = [];
  const pushPart = (part: string) => {
    const cleaned = part.trim();
    if (!cleaned) return;
    if (cleaned.length <= maxChars) {
      chunks.push(cleaned);
      return;
    }
    const sentences = cleaned.match(/[^.!?。！？]+[.!?。！？]?/g) ?? [cleaned];
    let current = "";
    for (const sentence of sentences) {
      const next = current ? `${current}${sentence}` : sentence;
      if (next.length <= maxChars) {
        current = next;
        continue;
      }
      if (current.trim()) chunks.push(current.trim());
      if (sentence.length <= maxChars) {
        current = sentence;
      } else {
        for (let i = 0; i < sentence.length; i += maxChars) {
          chunks.push(sentence.slice(i, i + maxChars).trim());
        }
        current = "";
      }
    }
    if (current.trim()) chunks.push(current.trim());
  };

  for (const paragraph of text.split(/\n{2,}/)) {
    pushPart(paragraph);
  }
  return chunks;
}

function markdownTextForTranslation(markdown: string): string {
  return normalizeTranslationText(
    markdown
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, "$2$1")
      .replace(/[`*_~>#-]/g, " ")
      .replace(/^\s*\d+\.\s+/gm, "")
      .replace(/^\s*[-+*]\s+/gm, ""),
  );
}

export function splitMarkdownBlocks(markdown: string): MarkdownBlock[] {
  return markdown
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      if (/^```/.test(part) || /^\|.*\|/m.test(part) || /^!\[/.test(part)) {
        return { markdown: part, text: "", kind: "skip" };
      }
      const heading = part.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        const text = markdownTextForTranslation(heading[2]);
        return {
          markdown: part,
          text,
          kind: isTranslatableText(text) ? "heading" : "skip",
          headingPrefix: heading[1],
        };
      }
      const text = markdownTextForTranslation(part);
      return {
        markdown: part,
        text,
        kind: isTranslatableText(text) ? "text" : "skip",
      };
    });
}

export function bilingualMarkdown(blocks: MarkdownBlock[], translations: Map<number, string>): string {
  return blocks
    .map((block, index) => {
      const translated = translations.get(index);
      if (!translated) return block.markdown;
      if (block.kind === "heading" && block.headingPrefix) {
        return `${block.markdown}\n\n${block.headingPrefix} ${translated}`;
      }
      return `${block.markdown}\n\n${translated}`;
    })
    .join("\n\n");
}

export function splitMarkdownChunks(blocks: MarkdownBlock[], maxChars = 2200): MarkdownChunk[] {
  const chunks: MarkdownChunk[] = [];
  let pending: MarkdownBlock[] = [];
  let pendingChars = 0;

  const flush = () => {
    if (!pending.length) return;
    chunks.push({
      kind: "translate",
      markdown: pending.map((block) => block.markdown).join("\n\n"),
      text: pending.map((block) => block.markdown).join("\n\n"),
    });
    pending = [];
    pendingChars = 0;
  };

  for (const block of blocks) {
    if (block.kind === "skip") {
      flush();
      chunks.push({ kind: "skip", markdown: block.markdown, text: "" });
      continue;
    }
    const extra = block.markdown.length + (pending.length ? 2 : 0);
    if (pending.length && pendingChars + extra > maxChars) flush();
    pending.push(block);
    pendingChars += extra;
  }
  flush();
  return chunks;
}

export function bilingualChunkMarkdown(chunks: MarkdownChunk[], translations: Map<number, string>): string {
  return chunks
    .map((chunk, index) => {
      const translated = translations.get(index);
      return translated ? `${chunk.markdown}\n\n${translated}` : chunk.markdown;
    })
    .join("\n\n");
}

function hashString(value: string): string {
  let hash = 5381;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 33) ^ value.charCodeAt(i);
  }
  return (hash >>> 0).toString(36);
}

export function noteTranslationCacheKey(path: string, content: string): string {
  return `${NOTE_TRANSLATION_CACHE_PREFIX}${path}:${hashString(content)}`;
}
