import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";
import { Icon } from "./icons";
import type { Citation } from "./types";

export const TRUST_LABEL: Record<number, string> = {
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
    <span className={`badge trust${level}`} title={`Trust level ${level}`}>
      {TRUST_LABEL[level] ?? `trust ${level}`}
    </span>
  );
}

/** True when a cited page can be shown as an image (PDF / slide decks). */
export function hasPageImage(path: string, documentId?: number | null, page?: number | null) {
  return documentId != null && page != null && /\.(pdf|pptx|ppt)$/i.test(path);
}

export function SourcePageViewer({
  documentId,
  page,
  title,
  onClose,
}: {
  documentId: number;
  page: number;
  title: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  // Portal to <body> so an animated/transformed ancestor can't trap the overlay.
  return createPortal(
    <div className="lecture-viewer-backdrop" role="presentation" onClick={onClose}>
      <section
        className="lecture-viewer"
        role="dialog"
        aria-modal="true"
        aria-label={`${title}, page ${page}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="lecture-viewer-toolbar">
          <div className="lecture-viewer-title"><span>{title} · Page {page}</span></div>
          <button type="button" className="icon-btn" aria-label="Close page" onClick={onClose}>
            <Icon name="x" />
          </button>
        </header>
        <div className="lecture-viewer-canvas">
          <img
            src={api.sourcePageUrl(documentId, page)}
            alt={`${title}, page ${page}`}
            style={{ maxWidth: "100%" }}
          />
        </div>
      </section>
    </div>,
    document.body,
  );
}

export function CitationLine({ cite }: { cite: Citation }) {
  const [showPage, setShowPage] = useState(false);
  const wk = cite.week != null ? ` · Week ${cite.week}` : "";
  const hasPage = hasPageImage(cite.path, cite.document_id, cite.page_number);
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
        <SourcePageViewer
          documentId={cite.document_id!}
          page={cite.page_number!}
          title={cite.title}
          onClose={() => setShowPage(false)}
        />
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

/** Close a popover on outside click or Escape. */
export function useDismiss(
  open: boolean,
  onClose: () => void,
  refs: RefObject<HTMLElement>[],
) {
  const latest = useRef(onClose);
  latest.current = onClose;
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (refs.some((ref) => ref.current?.contains(target))) return;
      latest.current();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") latest.current();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}
