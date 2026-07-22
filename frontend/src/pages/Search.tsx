import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import type { Citation, Job, SearchResponse } from "../types";
import { CitationLine, TrustBadge, Warnings } from "../components";
import { CoursePicker } from "../CoursePicker";
import type { VaultScope } from "../types";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";

function safeName(value: string) {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 70) || "deep-answer"
  );
}

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<VaultScope | null>(null);
  const [maxTrust, setMaxTrust] = useState<string>("");
  const [resp, setResp] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [deepJob, setDeepJob] = useState<Job | null>(null);
  const [deepSavedPath, setDeepSavedPath] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!deepJob || !["queued", "running"].includes(deepJob.status)) return;
    const timer = window.setTimeout(() => {
      api.job(deepJob.id).then(setDeepJob).catch((e) => setError((e as Error).message));
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [deepJob]);

  const run = async () => {
    if (!query.trim() || loading) return;
    setError(null);
    setLoading(true);
    try {
      const r = await api.search({
        query,
        course: scope?.course ?? null,
        scope_path: scope?.kind === "study_set" ? null : scope?.path ?? null,
        study_set_id: scope?.study_set_id ?? null,
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

  const runDeep = async () => {
    if (!query.trim() || deepLoading) return;
    setError(null);
    setDeepSavedPath(null);
    setDeepLoading(true);
    try {
      const job = await api.deepAsk({
        question: query,
        course: scope?.course ?? null,
        scope_path: scope?.kind === "study_set" ? null : scope?.path ?? null,
        study_set_id: scope?.study_set_id ?? null,
      });
      setDeepJob(job);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDeepLoading(false);
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

  const saveDeepAnswer = async () => {
    if (deepJob?.status !== "succeeded" || !deepJob.result) return;
    setError(null);
    try {
      const path = `StudyCopilot/Generated Notes/Deep Ask/${safeName(query)}.md`;
      const citations = Array.isArray(deepJob.result.citations)
        ? deepJob.result.citations as Citation[]
        : [];
      const content = [
        "---",
        `title: Deep Answer - ${query.replace(/"/g, "'")}`,
        "type: deep-answer",
        "generated_by: Study Copilot",
        "---",
        "",
        `# Deep Answer - ${query}`,
        "",
        String(deepJob.result.answer ?? ""),
        "",
        "## Sources",
        "",
        ...citations.map((citation) => `- [[${citation.path}|${citation.title}]]`),
        "",
      ].join("\n");
      await api.vaultSaveNote(path, content);
      setDeepSavedPath(path);
    } catch (e) {
      setError((e as Error).message);
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
          <button onClick={runDeep} disabled={deepLoading || !query.trim()}>
            {deepLoading ? "Starting..." : "Deep Answer"}
          </button>
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

      {deepJob && (
        <div className="preview" style={{ marginTop: 14 }}>
          <div className="row small muted" style={{ marginBottom: 8 }}>
            <span>Deep answer job #{deepJob.id}</span>
            <span>{deepJob.status}</span>
            {deepJob.progress_total > 0 && (
              <span>
                {deepJob.progress_current}/{deepJob.progress_total}
              </span>
            )}
            {deepJob.message && <span>{deepJob.message}</span>}
          </div>
          {deepJob.status === "failed" && (
            <div className="warn-banner">{deepJob.error ?? "Deep answer failed."}</div>
          )}
          {deepJob.status === "succeeded" && deepJob.result && (
            <>
              <div className="md">
                <ReactMarkdown
                  remarkPlugins={mdRemarkPlugins}
                  rehypePlugins={mdRehypePlugins}
                  components={mdComponents}
                >
                  {String(deepJob.result.answer ?? "")}
                </ReactMarkdown>
              </div>
              {Array.isArray(deepJob.result.citations) && (
                <div className="citations">
                  {deepJob.result.citations.map((citation, index) => (
                    <CitationLine key={index} cite={citation as Citation} />
                  ))}
                </div>
              )}
              {Array.isArray(deepJob.result.warnings) && (
                <Warnings items={deepJob.result.warnings as string[]} />
              )}
              <div className="row" style={{ marginTop: 10 }}>
                <button onClick={saveDeepAnswer}>Save to generated note</button>
                {deepSavedPath && (
                  <span className="small muted">
                    Saved to <code>{deepSavedPath}</code>
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}

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
