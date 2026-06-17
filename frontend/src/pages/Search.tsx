import { useState } from "react";
import { api } from "../api";
import type { SearchResponse } from "../types";
import { TrustBadge } from "../components";

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [course, setCourse] = useState("REIT6811");
  const [maxTrust, setMaxTrust] = useState<string>("");
  const [resp, setResp] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!query.trim() || loading) return;
    setError(null);
    setLoading(true);
    try {
      const r = await api.search({
        query,
        course: course || null,
        max_trust_level: maxTrust ? Number(maxTrust) : null,
        limit: 10,
        include_content: true,
      });
      setResp(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">Search</h1>
      <p className="page-sub">
        Hybrid retrieval (keyword + vector), trust-weighted, with citations.
      </p>

      <div className="card">
        <div className="row">
          <input
            className="grow"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="Search your materials…"
          />
          <input
            value={course}
            onChange={(e) => setCourse(e.target.value)}
            placeholder="course"
            style={{ width: 120 }}
          />
          <select value={maxTrust} onChange={(e) => setMaxTrust(e.target.value)}>
            <option value="">any trust</option>
            <option value="1">official only (≤1)</option>
            <option value="3">≤ past-paper (≤3)</option>
            <option value="5">≤ user-note (≤5)</option>
          </select>
          <button className="primary" onClick={run} disabled={loading}>
            {loading ? "…" : "Search"}
          </button>
        </div>
      </div>

      {error && <div className="warn-banner" style={{ marginTop: 12 }}>{error}</div>}

      {resp && (
        <div style={{ marginTop: 18 }}>
          <div className="row small muted" style={{ marginBottom: 10 }}>
            <span>{resp.count} results</span>
            <span>·</span>
            <span>{resp.used_vector ? "hybrid (keyword + vector)" : "keyword-only"}</span>
            {resp.note && <span>· {resp.note}</span>}
          </div>
          {resp.results.map((h) => (
            <div className="result" key={h.chunk_id}>
              <h4>{h.title}</h4>
              <div className="meta">
                <span className="link" style={{ color: "var(--accent)" }}>
                  {h.citation.link}
                </span>
                {h.citation.location && <span>{h.citation.location}</span>}
                <TrustBadge level={h.trust_level} />
                <span>score {h.score.toFixed(3)}</span>
              </div>
              {h.content && <div className="snippet">{h.content}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
