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
  const wk = cite.week != null ? ` · Week ${cite.week}` : "";
  return (
    <div className="cite">
      <span className="link">{cite.link}</span>
      {cite.location ? ` — ${cite.location}` : ""}
      {cite.course ? ` · ${cite.course}${wk}` : ""}{" "}
      <TrustBadge level={cite.trust_level} />
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
