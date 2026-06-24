import { useState } from "react";
import { api } from "../api";
import type { SearchResponse } from "../types";
import { TrustBadge } from "../components";
import { CoursePicker } from "../CoursePicker";
import type { VaultScope } from "../types";

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [maxTrust, setMaxTrust] = useState<string>("");
  const [resp, setResp] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!query.trim() || loading) return;
    setError(null);
    setLoading(true);
    try {
      const r = await api.search({
        query,
        course: scope?.course ?? null,
        scope_path: scope?.path ?? null,
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

  const openResult = async (path: string) => {
    if (opening) return;
    setOpening(path);
    setError(null);
    try {
      await api.vaultOpenExternal(path);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOpening(null);
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
          <CoursePicker value={scope} onChange={setScope} />
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
            <div
              className="result search-result-open"
              key={h.chunk_id}
              role="button"
              tabIndex={0}
              title={`Open ${h.title}`}
              onClick={() => openResult(h.path)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") openResult(h.path);
              }}
            >
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
              {opening === h.path && <div className="small muted">Opening…</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
