// Markdown components for reading view: clickable [[wikilinks]] (unresolved
// ones create the note), relative note links, ![[embeds]], and heading ids so
// "#heading" jumps and the outline work.

import { useMemo } from "react";
import type { Components } from "react-markdown";
import { NoteEmbed, unwrapEmbedParagraph } from "../../NoteEmbed";
import { folderOf, slug, toText } from "./paths";

export function useWikiComponents({
  linkMap,
  notePath,
  openLinkedNote,
  openExternalUrl,
}: {
  /** Lower-cased link name -> resolved path (null when it doesn't exist). */
  linkMap: Record<string, string | null>;
  notePath: string | undefined;
  openLinkedNote: (target: string, newTab?: boolean) => Promise<void>;
  openExternalUrl: (url: string) => Promise<void>;
}): Components {
  return useMemo(() => {
    const heading = (Tag: "h1" | "h2" | "h3" | "h4" | "h5" | "h6") =>
      ({ children }: any) => <Tag id={slug(toText(children))}>{children}</Tag>;
    const currentDir = folderOf(notePath);
    return {
      a: ({ href, children }: any) => {
        if (href?.startsWith("wikilink:")) {
          const name = decodeURIComponent(href.slice("wikilink:".length));
          const [base] = name.split("#", 2);
          const resolved = linkMap[base.toLowerCase()];
          const unresolved =
            resolved === null && !/\.(?!md$|markdown$|txt$)[a-z0-9]{1,6}$/i.test(base);
          return (
            <span
              className={`wikilink${unresolved ? " wikilink-unresolved" : ""}`}
              title={unresolved ? `"${base}" doesn't exist yet — click to create it` : undefined}
              onClick={(e) => void openLinkedNote(name, e.ctrlKey || e.metaKey)}
            >
              {children}
            </span>
          );
        }
        const raw = decodeURIComponent(href ?? "");
        const isTauriPlaceholder = /^https?:\/\/tauri\.localhost\/?$/i.test(raw);
        const isWeb = /^(https?:|mailto:)/i.test(raw) && !isTauriPlaceholder;
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
      p: unwrapEmbedParagraph,
      img: ({ src, alt }: any) => {
        if (src?.startsWith("wikilink:")) {
          const target = decodeURIComponent(src.slice("wikilink:".length));
          return (
            <NoteEmbed
              target={target}
              resolve={(base) => linkMap[base.toLowerCase()] ?? null}
              currentDir={currentDir}
              depth={0}
              onOpen={(t, newTab) => void openLinkedNote(t, newTab)}
            />
          );
        }
        return <img src={src} alt={alt} />;
      },
      h1: heading("h1"),
      h2: heading("h2"),
      h3: heading("h3"),
      h4: heading("h4"),
      h5: heading("h5"),
      h6: heading("h6"),
    };
  }, [linkMap, notePath, openExternalUrl, openLinkedNote]);
}
