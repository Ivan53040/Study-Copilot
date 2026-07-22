// Shared markdown configuration: GFM tables, Obsidian callouts, syntax
// highlighting, and Mermaid diagram rendering.
import { useEffect, useRef, useState } from "react";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkCallouts from "remark-obsidian-callout";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import mermaid from "mermaid";
import "katex/dist/katex.min.css";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
  fontFamily: "inherit",
});

export function nodeText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(nodeText).join("");
  if (children && typeof children === "object" && "props" in (children as any))
    return nodeText((children as any).props.children);
  return "";
}

function Mermaid({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const id = "mmd-" + Math.random().toString(36).slice(2);
    mermaid
      .render(id, code)
      .then(({ svg }) => {
        if (alive && ref.current) ref.current.innerHTML = svg;
      })
      .catch((e) => alive && setError(String(e?.message ?? e)));
    return () => {
      alive = false;
    };
  }, [code]);
  if (error) return <pre className="mermaid-error">{code}</pre>;
  return <div className="mermaid" ref={ref} />;
}

export function stripFrontmatter(raw: string): string {
  if (raw.startsWith("---")) {
    const end = raw.indexOf("\n---", 3);
    if (end !== -1) {
      const nl = raw.indexOf("\n", end + 1);
      return nl !== -1 ? raw.slice(nl + 1) : "";
    }
  }
  return raw;
}

// Rewrite [[Name#Heading|alias]] wikilinks to markdown links with a wikilink:
// scheme, so a custom `a` component can resolve and open them. The #heading is
// kept in the target; embeds (![[Name]]) become images a custom `img` handles.
export function wikilinksToMd(text: string): string {
  return text.replace(
    /\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]+))?\]\]/g,
    (_m, name: string, heading?: string, alias?: string) => {
      const target = name.trim() + (heading ?? "").trim();
      const label =
        alias?.trim() ||
        (heading
          ? `${name.trim()} › ${heading.slice(1).trim()}`
          : name.trim());
      return `[${label}](wikilink:${encodeURIComponent(target)})`;
    },
  );
}

export const mdRemarkPlugins = [remarkGfm, remarkMath, remarkCallouts] as any[];
// rehype-raw first so callout title HTML becomes real nodes; KaTeX renders
// $...$ and $$...$$ math before syntax highlighting handles code blocks.
export const mdRehypePlugins = [rehypeRaw, rehypeKatex, rehypeHighlight] as any[];

// Base components: render ```mermaid blocks as diagrams; keep highlight classes
// on all other code.
export const mdComponents: Components = {
  code({ className, children, ...props }: any) {
    if (className && className.includes("language-mermaid")) {
      return <Mermaid code={nodeText(children).replace(/\n$/, "")} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
};
