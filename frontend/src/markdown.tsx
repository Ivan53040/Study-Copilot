// Shared markdown configuration: GFM tables, Obsidian callouts, syntax
// highlighting, and Mermaid diagram rendering.
import { useEffect, useRef, useState } from "react";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkCallouts from "remark-obsidian-callout";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import mermaid from "mermaid";

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

export const mdRemarkPlugins = [remarkGfm, remarkCallouts] as any[];
// rehype-raw first so the callout title HTML becomes real nodes, then highlight.
export const mdRehypePlugins = [rehypeRaw, rehypeHighlight] as any[];

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
