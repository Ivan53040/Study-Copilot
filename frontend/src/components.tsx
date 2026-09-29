import { useEffect, useState } from "react";
import { api } from "./api";
import type { Citation } from "./types";

const TRUST_LABEL: Record<number, string> = {
  1: "official",
  2: "rubric",
  3: "past-paper",
  4: "feedback",
  5: "user-note",
  6: "reviewed-ai",
  7: "ai-generated",
  8: "external",
};

export function TrustBadge({ level }: { level: number }) {
  return (
    <span className={`badge trust${level}`}>
      trust {level} · {TRUST_LABEL[level] ?? "?"}
    </span>
  );
}

export function CitationLine({ cite }: { cite: Citation }) {
  const [showPage, setShowPage] = useState(false);
  useEffect(() => {
    if (!showPage) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setShowPage(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [showPage]);
  const wk = cite.week != null ? ` · Week ${cite.week}` : "";
  const hasPage = cite.document_id != null && cite.page_number != null &&
    /\.(pdf|pptx|ppt)$/i.test(cite.path);
  return (
    <div className="cite">
      {hasPage ? (
        <button type="button" className="citation-page-link" onClick={() => setShowPage(true)}>
          {cite.link}
        </button>
      ) : <span className="link">{cite.link}</span>}
      {cite.location ? ` — ${cite.location}` : ""}
      {cite.course ? ` · ${cite.course}${wk}` : ""}{" "}
      <TrustBadge level={cite.trust_level} />
      {showPage && hasPage && (
        <div className="lecture-viewer-backdrop" role="presentation" onClick={() => setShowPage(false)}>
          <section className="lecture-viewer" role="dialog" aria-modal="true" aria-label={`${cite.title}, page ${cite.page_number}`} onClick={(event) => event.stopPropagation()}>
            <header className="lecture-viewer-toolbar">
              <div className="lecture-viewer-title"><span>{cite.title} · Page {cite.page_number}</span></div>
              <button type="button" className="lecture-viewer-close" aria-label="Close page" onClick={() => setShowPage(false)}>×</button>
            </header>
            <div className="lecture-viewer-canvas">
              <img src={api.sourcePageUrl(cite.document_id!, cite.page_number!)} alt={`${cite.title}, page ${cite.page_number}`} style={{ maxWidth: "100%" }} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export function Warnings({ items }: { items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="warn-banner" style={{ marginTop: 8 }}>
      ⚠ {items.join(" · ")}
    </div>
  );
}
