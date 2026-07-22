import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import { WikiForceGraph } from "../WikiForceGraph";
import type {
  CourseSummary,
  Job,
  MentionGroup,
  MentionSpan,
  NoteMentions,
  VaultScope,
  WikiBacklinkReview,
  WikiBacklinkReviewTarget,
  WikiGraph,
  WikiPage as WikiPageInfo,
  WikiPagesResponse,
} from "../types";
import {
  mdComponents,
  mdRehypePlugins,
  mdRemarkPlugins,
  stripFrontmatter,
  wikilinksToMd,
} from "../markdown";

const TYPE_GROUPS: { type: WikiPageInfo["type"]; label: string }[] = [
  { type: "map", label: "Course Maps" },
  { type: "concept", label: "Concepts" },
  { type: "entity", label: "Entities" },
  { type: "source", label: "Sources" },
];

const PURPOSE_STUB = `# Wiki Purpose

Describe what this wiki is for: your goals, key questions, and what the LLM
should focus on when building pages. This file is read before every build.
`;

// What the user picked to build/view: everything, one course, or one folder.
type WikiSel =
  | { kind: "all"; label: null }
  | { kind: "course"; label: string; course: string }
  | { kind: "folder"; label: string; scopePath: string; name: string };

function scopeDepth(id: string): number {
  const rel = id.startsWith("folder:") ? id.slice("folder:".length) : id;
  return rel.split("/").filter(Boolean).length;
}

export function WikiPage({ onOpenNote }: { onOpenNote: (path: string) => void }) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [folders, setFolders] = useState<VaultScope[]>([]);
  const [selKey, setSelKey] = useState<string>("all");
  const [data, setData] = useState<WikiPagesResponse | null>(null);
  const [graph, setGraph] = useState<WikiGraph | null>(null);
  const [view, setView] = useState<"pages" | "graph">("pages");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");
  const [filter, setFilter] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linkReview, setLinkReview] = useState<NoteMentions | null>(null);
  const [batchLinkReview, setBatchLinkReview] = useState<WikiBacklinkReview | null>(null);
  const [linkReviewTitle, setLinkReviewTitle] = useState("");
  const [linkReviewAliases, setLinkReviewAliases] = useState<string[]>([]);
  const [linkReviewLoading, setLinkReviewLoading] = useState(false);
  const [linkingMention, setLinkingMention] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    // Courses drive study wikis; unclassified notes live under folders instead.
    api
      .courses()
      .then((r) => setCourses(r.courses.filter((c) => c.course !== "(unclassified)")))
      .catch(() => {});
    api
      .scopes()
      .then((r) =>
        setFolders(
          r.scopes.filter(
            (s) => s.kind === "folder" && s.documents > 0 && scopeDepth(s.id) <= 2,
          ),
        ),
      )
      .catch(() => {});
  }, []);

  const sel: WikiSel = useMemo(() => {
    if (selKey === "all") return { kind: "all", label: null };
    const idx = selKey.indexOf(":");
    const kind = selKey.slice(0, idx);
    const rest = selKey.slice(idx + 1);
    if (kind === "course") return { kind: "course", label: rest, course: rest };
    const folder = folders.find((f) => f.path === rest);
    const name = folder?.name ?? rest.split(/[\\/]/).filter(Boolean).pop() ?? "Notes";
    return { kind: "folder", label: name, scopePath: rest, name };
  }, [selKey, folders]);

  const refresh = useCallback(() => {
    api
      .wikiPages(sel.label)
      .then((r) => {
        setData(r);
        setSelectedPath((prev) =>
          prev && r.pages.some((p) => p.path === prev) ? prev : r.pages[0]?.path ?? null,
        );
      })
      .catch((e) => setError((e as Error).message));
    api
      .wikiGraph(sel.label)
      .then(setGraph)
      .catch(() => setGraph(null));
  }, [sel.label]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    if (!selectedPath) {
      setContent("");
      return;
    }
    let alive = true;
    api
      .vaultNote(selectedPath)
      .then((note) => alive && setContent(note.content))
      .catch((e) => alive && setContent(`*Could not load page: ${(e as Error).message}*`));
    return () => {
      alive = false;
    };
  }, [selectedPath]);

  // Poll the build job until it finishes, then refresh the page list.
  useEffect(() => {
    if (!job || job.status === "succeeded" || job.status === "failed" || job.status === "cancelled") {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = window.setInterval(() => {
      api
        .job(job.id)
        .then((next) => {
          setJob(next);
          if (next.status === "succeeded") {
            if (next.type === "wiki_link_review") {
              setBatchLinkReview(next.result as unknown as WikiBacklinkReview);
            } else {
              refresh();
            }
          }
        })
        .catch(() => {});
    }, 1500);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [job?.id, job?.status, refresh]);

  const build = async (force: boolean) => {
    setError(null);
    try {
      const body =
        sel.kind === "course"
          ? { course: sel.course, force }
          : sel.kind === "folder"
            ? { scope_path: sel.scopePath, name: sel.name, force }
            : { force };
      setJob(await api.wikiBuild(body));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const openPurpose = async () => {
    if (!data) return;
    try {
      if (!data.has_purpose) await api.vaultSaveNote(data.purpose_path, PURPOSE_STUB);
      onOpenNote(data.purpose_path);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const titleMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const page of data?.pages ?? []) map[page.title.toLowerCase()] = page.path;
    return map;
  }, [data]);

  // Wikilinks resolve inside this wiki first, then fall back to the Notes tab.
  const wikiAnchor = useCallback(
    ({ href, children }: any) => {
      if (href?.startsWith("wikilink:")) {
        const name = decodeURIComponent(href.slice("wikilink:".length));
        const target = titleMap[name.toLowerCase()];
        return (
          <span
            className="wikilink"
            onClick={() => (target ? setSelectedPath(target) : onOpenNote(name))}
          >
            {children}
          </span>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
    [titleMap, onOpenNote],
  );

  const selected = data?.pages.find((p) => p.path === selectedPath) ?? null;
  const openLinkReview = async () => {
    if (!selected) return;
    const aliases = selected.title ? [selected.title] : [];
    setError(null);
    setLinkReviewLoading(true);
    setLinkReviewTitle(selected.title);
    setLinkReviewAliases(aliases);
    try {
      setLinkReview(await api.vaultBacklinkReview(selected.path, aliases));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinkReviewLoading(false);
    }
  };

  const reviewAllLinks = async () => {
    setError(null);
    setBatchLinkReview(null);
    try {
      setJob(await api.wikiBacklinkReview(sel.label));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const approveWikiMention = async (group: MentionGroup, mention: MentionSpan) => {
    if (!linkReview) return;
    const key = `${group.path}:${mention.line}:${mention.start}:${mention.end}`;
    setLinkingMention(key);
    setError(null);
    try {
      await api.vaultLinkMention({
        source_path: group.path,
        target_path: linkReview.path,
        line: mention.line,
        start: mention.start,
        end: mention.end,
        aliases: linkReviewAliases,
      });
      setLinkReview(await api.vaultBacklinkReview(linkReview.path, linkReviewAliases));
      if (group.path === selectedPath) {
        const note = await api.vaultNote(group.path);
        setContent(note.content);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinkingMention(null);
    }
  };

  const approveBatchMention = async (
    target: WikiBacklinkReviewTarget,
    group: MentionGroup,
    mention: MentionSpan,
  ) => {
    const key = `${target.path}:${group.path}:${mention.line}:${mention.start}:${mention.end}`;
    setLinkingMention(key);
    setError(null);
    try {
      await api.vaultLinkMention({
        source_path: group.path,
        target_path: target.path,
        line: mention.line,
        start: mention.start,
        end: mention.end,
        aliases: target.aliases,
      });
      setBatchLinkReview((current) => {
        if (!current) return current;
        return {
          ...current,
          targets: current.targets
            .map((item) =>
              item.path !== target.path
                ? item
                : {
                    ...item,
                    review: {
                      ...item.review,
                      unlinked: item.review.unlinked
                        .map((source) =>
                          source.path !== group.path
                            ? source
                            : {
                                ...source,
                                mentions: source.mentions.filter(
                                  (itemMention) =>
                                    itemMention.line !== mention.line ||
                                    itemMention.start !== mention.start ||
                                    itemMention.end !== mention.end,
                                ),
                              },
                        )
                        .filter((source) => source.mentions.length > 0),
                    },
                  },
            )
            .filter((item) => item.review.unlinked.length > 0),
        };
      });
      if (group.path === selectedPath) {
        const note = await api.vaultNote(group.path);
        setContent(note.content);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLinkingMention(null);
    }
  };

  const building = job !== null && (job.status === "queued" || job.status === "running");
  const query = filter.trim().toLowerCase();
  const visible = (data?.pages ?? []).filter(
    (p) => !query || p.title.toLowerCase().includes(query) || p.summary.toLowerCase().includes(query),
  );
  const unlinkedReviewCount =
    linkReview?.unlinked.reduce((sum, group) => sum + group.mentions.length, 0) ?? 0;
  return (
    <div className="wiki-page">
      <div className="graph-header">
        <div>
          <h1 className="page-title">Wiki</h1>
          <p className="page-sub">
            An LLM-built knowledge base from your notes — pick a course or any
            vault folder (side projects, personal notes) and it builds
            interlinked concept and entity pages, rebuilt incrementally.
          </p>
        </div>
        <div className="graph-controls">
          <select value={selKey} onChange={(e) => setSelKey(e.target.value)}>
            <option value="all">View all</option>
            {courses.length > 0 && (
              <optgroup label="Courses">
                {courses.map((c) => (
                  <option key={c.course} value={`course:${c.course}`}>
                    {c.label || c.course}
                  </option>
                ))}
              </optgroup>
            )}
            {folders.length > 0 && (
              <optgroup label="Folders">
                {folders.map((f) => (
                  <option key={f.path} value={`folder:${f.path}`}>
                    {f.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <button onClick={() => setView(view === "pages" ? "graph" : "pages")}>
            {view === "pages" ? "Graph view" : "Page view"}
          </button>
          <button onClick={openPurpose} title="Edit the purpose.md fed to every build">
            Purpose
          </button>
          <button onClick={() => build(false)} disabled={building}>
            {building ? "Building…" : "Build wiki"}
          </button>
          <button
            onClick={() => build(true)}
            disabled={building}
            title="Reprocess every source, ignoring unchanged-content skips"
          >
            Rebuild all
          </button>
          <button onClick={reviewAllLinks} disabled={building} title="Review all concept and entity pages with the local AI">
            Link all
          </button>
        </div>
      </div>

      {error && <div className="warn-banner">{error}</div>}
      {job && (
        <div className={job.status === "failed" ? "warn-banner" : "note-banner"}>
          {job.status === "failed"
            ? `${job.type === "wiki_link_review" ? "AI link review" : "Build"} failed: ${job.error ?? "unknown error"}`
            : job.type === "wiki_link_review" && job.status === "succeeded"
              ? `AI link review complete - ${String((job.result as any)?.suggestions ?? 0)} suggestions across ${String((job.result as any)?.pages_reviewed ?? 0)} pages.`
            : job.status === "succeeded"
              ? `Build complete — ${String((job.result as any)?.processed ?? 0)} processed, ${String((job.result as any)?.skipped ?? 0)} unchanged, ${String((job.result as any)?.failed ?? 0)} failed.`
              : `${job.message ?? "Working…"} (${job.progress_current}/${job.progress_total})`}
        </div>
      )}

      {view === "graph" ? (
        graph && graph.nodes.length > 0 ? (
          <WikiForceGraph
            graph={graph}
            onOpenPage={(path) => {
              setSelectedPath(path);
              setView("pages");
            }}
          />
        ) : (
          <p className="muted">No wiki pages yet — run a build first.</p>
        )
      ) : (
        <div className="wiki-layout">
          <aside className="wiki-list">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter pages…"
            />
            {TYPE_GROUPS.map(({ type, label }) => {
              const group = visible.filter((p) => p.type === type);
              if (!group.length) return null;
              return (
                <div key={type}>
                  <div className="wiki-group-label">{label}</div>
                  {group.map((page) => (
                    <button
                      key={page.path}
                      className={`wiki-item ${page.path === selectedPath ? "active" : ""}`}
                      onClick={() => setSelectedPath(page.path)}
                      title={page.summary}
                    >
                      {page.title}
                    </button>
                  ))}
                </div>
              );
            })}
            {!data?.pages.length && (
              <p className="muted small">
                No pages yet. Pick a course or folder and press “Build wiki” —
                sources are analyzed and turned into linked pages.
              </p>
            )}
          </aside>
          <section className="wiki-content">
            {selected ? (
              <>
                <div className="wiki-meta">
                  <span className={`wiki-chip wiki-chip-${selected.type}`}>{selected.type}</span>
                  <span className="muted small">
                    {selected.sources.length} source{selected.sources.length === 1 ? "" : "s"}
                    {selected.updated_at && <> · updated {selected.updated_at}</>}
                  </span>
                  <div className="grow" />
                  <button onClick={openLinkReview} disabled={linkReviewLoading}>
                    {linkReviewLoading ? "Reviewing..." : "Link with AI"}
                  </button>
                  <button onClick={() => onOpenNote(selected.path)}>Open in Notes</button>
                </div>
                <div className="md">
                  <ReactMarkdown
                    remarkPlugins={mdRemarkPlugins}
                    rehypePlugins={mdRehypePlugins}
                    components={{ ...mdComponents, a: wikiAnchor }}
                    urlTransform={(url) => url}
                  >
                    {wikilinksToMd(stripFrontmatter(content))}
                  </ReactMarkdown>
                </div>
              </>
            ) : (
              <p className="muted">Select a page.</p>
            )}
          </section>
        </div>
      )}
      {linkReview && (
        <div className="organizer-backdrop">
          <div className="organizer-modal backlink-review-modal card">
            <div className="row">
              <div>
                <h2 className="page-title">Approve AI backlinks</h2>
                <p className="page-sub">
                  {linkReviewTitle || linkReview.name} - {unlinkedReviewCount} relevant of{" "}
                  {linkReview.candidates ?? 0} matches reviewed
                  {linkReview.model ? ` by ${linkReview.model}` : ""}
                </p>
              </div>
              <div className="grow" />
              <button onClick={() => setLinkReview(null)}>Close</button>
            </div>
            <div className="backlink-review-results">
              {linkReview.notice && <div className="warn-banner">{linkReview.notice}</div>}
              {unlinkedReviewCount === 0 && (
                <div className="note-banner">
                  No high-confidence source mentions found for {linkReviewTitle || linkReview.name}.
                </div>
              )}
              {linkReview.unlinked.map((group) => (
                <section className="backlink-target" key={group.path}>
                  <div className="backlink-target-header">
                    <button
                      className="linked-note backlink-target-title"
                      onClick={() => onOpenNote(group.path)}
                    >
                      {group.title}
                    </button>
                    <span className="muted small">{group.path}</span>
                    <span className="pill">{group.mentions.length}</span>
                  </div>
                  {group.mentions.map((mention) => {
                    const key = `${group.path}:${mention.line}:${mention.start}:${mention.end}`;
                    return (
                      <div
                        key={key}
                        className="mention-snippet mention-unlinked backlink-review-hit"
                      >
                        <span onClick={() => onOpenNote(group.path)}>
                          {mention.snippet.slice(0, mention.hl_start)}
                          <mark>{mention.snippet.slice(mention.hl_start, mention.hl_end)}</mark>
                          {mention.snippet.slice(mention.hl_end)}
                        </span>
                        {mention.reason && <span className="muted small">{mention.reason}</span>}
                        <button
                          className="mention-link-btn"
                          disabled={linkingMention === key}
                          onClick={() => void approveWikiMention(group, mention)}
                        >
                          {linkingMention === key ? "Linking..." : "Link"}
                        </button>
                      </div>
                    );
                  })}
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
      {batchLinkReview && (
        <div className="organizer-backdrop">
          <div className="organizer-modal backlink-review-modal card">
            <div className="row">
              <div>
                <h2 className="page-title">Approve AI backlinks</h2>
                <p className="page-sub">
                  {batchLinkReview.suggestions} suggestions across {batchLinkReview.pages_reviewed} wiki pages
                </p>
              </div>
              <div className="grow" />
              <button onClick={() => setBatchLinkReview(null)}>Close</button>
            </div>
            <div className="backlink-review-results">
              {batchLinkReview.errors.length > 0 && (
                <div className="warn-banner">{batchLinkReview.errors.length} pages could not be reviewed.</div>
              )}
              {batchLinkReview.targets.length === 0 && (
                <div className="note-banner">No high-confidence source mentions found.</div>
              )}
              {batchLinkReview.targets.map((target) => (
                <section className="backlink-target" key={target.path}>
                  <div className="backlink-target-header">
                    <strong>{target.title}</strong>
                    <span className="pill">
                      {target.review.unlinked.reduce((count, group) => count + group.mentions.length, 0)}
                    </span>
                  </div>
                  {target.review.unlinked.map((group) => (
                    <div key={group.path}>
                      <div className="backlink-target-header">
                        <button className="linked-note backlink-target-title" onClick={() => onOpenNote(group.path)}>
                          {group.title}
                        </button>
                        <span className="muted small">{group.path}</span>
                      </div>
                      {group.mentions.map((mention) => {
                        const key = `${target.path}:${group.path}:${mention.line}:${mention.start}:${mention.end}`;
                        return (
                          <div key={key} className="mention-snippet mention-unlinked backlink-review-hit">
                            <span onClick={() => onOpenNote(group.path)}>
                              {mention.snippet.slice(0, mention.hl_start)}
                              <mark>{mention.snippet.slice(mention.hl_start, mention.hl_end)}</mark>
                              {mention.snippet.slice(mention.hl_end)}
                            </span>
                            {mention.reason && <span className="muted small">{mention.reason}</span>}
                            <button
                              className="mention-link-btn"
                              disabled={linkingMention === key}
                              onClick={() => void approveBatchMention(target, group, mention)}
                            >
                              {linkingMention === key ? "Linking..." : "Link"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
