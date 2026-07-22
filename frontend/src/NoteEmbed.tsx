// Obsidian-style transclusion: ![[Note]] / ![[Note#Heading]] rendered inline.
// Depth is capped so mutually-embedding notes degrade to plain links.
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { api } from "./api";
import {
  mdComponents,
  mdRehypePlugins,
  mdRemarkPlugins,
  stripFrontmatter,
  wikilinksToMd,
} from "./markdown";
import type { VaultNote } from "./types";

const MAX_DEPTH = 2;
const NOTE_EXTS = ["md", "markdown", "txt"];

const withExtension = (value: string) =>
  /\.(md|markdown|txt)$/i.test(value) ? value : `${value}.md`;

// Paragraphs whose only content is embed images must unwrap, so the embed's
// block markup isn't nested inside a <p>.
export const unwrapEmbedParagraph = ({ node, children, ...props }: any) => {
  const kids = node?.children ?? [];
  const onlyEmbeds =
    kids.length > 0 &&
    kids.every(
      (k: any) =>
        (k.tagName === "img" &&
          String(k.properties?.src ?? "").startsWith("wikilink:")) ||
        (k.type === "text" && !String(k.value).trim()),
    );
  return onlyEmbeds ? <>{children}</> : <p {...props}>{children}</p>;
};

// The section under `heading` (until the next heading of the same or higher
// level), or the whole body when the heading isn't found.
function sliceHeading(body: string, heading: string): string {
  const lines = body.split("\n");
  const wanted = heading.trim().toLowerCase();
  let start = -1;
  let level = 0;
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*(```|~~~)/.test(lines[i])) inFence = !inFence;
    if (inFence) continue;
    const m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(lines[i]);
    if (!m) continue;
    if (start === -1) {
      if (m[2].trim().toLowerCase() === wanted) {
        start = i;
        level = m[1].length;
      }
    } else if (m[1].length <= level) {
      return lines.slice(start, i).join("\n");
    }
  }
  return start === -1 ? body : lines.slice(start).join("\n");
}

interface NoteEmbedProps {
  target: string; // "Name", "Name#Heading", or a vault-relative path
  resolve: (base: string) => string | null;
  currentDir: string;
  depth: number;
  onOpen: (target: string, newTab: boolean) => void;
}

export function NoteEmbed({ target, resolve, currentDir, depth, onOpen }: NoteEmbedProps) {
  const [base, heading] = target.split("#", 2);
  const [note, setNote] = useState<VaultNote | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setNote(null);
    setFailed(false);
    if (depth >= MAX_DEPTH) return;
    const ext = /\.([a-z0-9]{1,6})$/i.exec(base)?.[1]?.toLowerCase();
    if (ext && !NOTE_EXTS.includes(ext)) {
      setFailed(true);
      return;
    }
    let alive = true;
    (async () => {
      const candidates = [
        resolve(base),
        withExtension(base),
        currentDir && !base.startsWith(currentDir)
          ? withExtension(currentDir + base)
          : null,
      ].filter((v, i, all): v is string => !!v && all.indexOf(v) === i);
      for (const candidate of candidates) {
        try {
          const fetched = await api.vaultNote(candidate);
          if (alive) setNote(fetched);
          return;
        } catch {
          // Try the next Obsidian-style resolution.
        }
      }
      if (alive) setFailed(true);
    })();
    return () => {
      alive = false;
    };
  }, [target, currentDir, depth]);

  const embedDir = note?.path.includes("/")
    ? note.path.slice(0, note.path.lastIndexOf("/") + 1)
    : "";

  const components: Components = useMemo(() => {
    const childResolve = (b: string) =>
      note?.links.find((l) => l.name.toLowerCase() === b.toLowerCase())?.path ?? null;
    return {
      ...mdComponents,
      p: unwrapEmbedParagraph,
      a: ({ href, children }: any) => {
        if (href?.startsWith("wikilink:")) {
          const name = decodeURIComponent(href.slice("wikilink:".length));
          return (
            <span
              className="wikilink"
              onClick={(e) => onOpen(name, e.ctrlKey || e.metaKey)}
            >
              {children}
            </span>
          );
        }
        return <a href={href}>{children}</a>;
      },
      img: ({ src, alt }: any) => {
        if (src?.startsWith("wikilink:")) {
          const nested = decodeURIComponent(src.slice("wikilink:".length));
          return (
            <NoteEmbed
              target={nested}
              resolve={childResolve}
              currentDir={embedDir}
              depth={depth + 1}
              onOpen={onOpen}
            />
          );
        }
        return <img src={src} alt={alt} />;
      },
    };
  }, [note, embedDir, depth, onOpen]);

  if (depth >= MAX_DEPTH || failed) {
    return (
      <span
        className={`wikilink${failed ? " wikilink-unresolved" : ""}`}
        onClick={(e) => onOpen(target, e.ctrlKey || e.metaKey)}
      >
        {target}
      </span>
    );
  }
  if (!note) {
    return <span className="small muted">Loading “{base}”…</span>;
  }

  const body = stripFrontmatter(note.content);
  const shown = heading ? sliceHeading(body, heading.trim()) : body;
  return (
    <div className="note-embed">
      <div
        className="note-embed-title"
        title="Open note"
        onClick={(e) => onOpen(target, e.ctrlKey || e.metaKey)}
      >
        {note.name}
        {heading ? ` › ${heading.trim()}` : ""}
      </div>
      <div className="md note-embed-body">
        <ReactMarkdown
          remarkPlugins={mdRemarkPlugins}
          rehypePlugins={mdRehypePlugins}
          components={components}
          urlTransform={(url) => url}
        >
          {wikilinksToMd(shown)}
        </ReactMarkdown>
      </div>
    </div>
  );
}
