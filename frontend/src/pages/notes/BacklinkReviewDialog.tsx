// "Search unlinked mentions": find plain-text mentions of a note title across
// the vault and approve each one as a [[wikilink]].

import { useState } from "react";
import { api } from "../../api";
import type {
  BacklinkSearchResponse,
  BacklinkSearchTarget,
  MentionGroup,
  MentionSpan,
} from "../../types";

const hitKey = (target: BacklinkSearchTarget, group: MentionGroup, mention: MentionSpan) =>
  `${target.path}:${group.path}:${mention.line}:${mention.start}:${mention.end}`;

/** Drop one approved mention from the results (and empty groups/targets). */
function withoutCandidate(
  previous: BacklinkSearchResponse | null,
  target: BacklinkSearchTarget,
  group: MentionGroup,
  mention: MentionSpan,
): BacklinkSearchResponse | null {
  if (!previous) return previous;
  const targets = previous.targets
    .map((candidate) => {
      if (candidate.path !== target.path) return candidate;
      const unlinked = candidate.unlinked
        .map((candidateGroup) => {
          if (candidateGroup.path !== group.path) return candidateGroup;
          return {
            ...candidateGroup,
            mentions: candidateGroup.mentions.filter(
              (item) =>
                !(
                  item.line === mention.line &&
                  item.start === mention.start &&
                  item.end === mention.end
                ),
            ),
          };
        })
        .filter((candidateGroup) => candidateGroup.mentions.length > 0);
      const count = unlinked.reduce((sum, item) => sum + item.mentions.length, 0);
      return { ...candidate, unlinked, count };
    })
    .filter((candidate) => candidate.count > 0);
  return {
    ...previous,
    targets,
    count: targets.length,
    mentions: targets.reduce((sum, candidate) => sum + candidate.count, 0),
  };
}

export function useBacklinkReview({
  flash,
  onLinked,
}: {
  flash: (message: string) => void;
  /** After a mention was linked: refresh whatever shows the affected notes. */
  onLinked: (target: BacklinkSearchTarget, group: MentionGroup) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [results, setResults] = useState<BacklinkSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [linking, setLinking] = useState<string | null>(null);

  const search = async (value = text) => {
    const query = value.trim();
    setText(value);
    if (query.length < 2) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      setResults(await api.vaultBacklinkSearch(query));
    } catch (e) {
      flash(String((e as Error).message ?? e));
    } finally {
      setSearching(false);
    }
  };

  /** Open the dialog, searching for `query` (usually the current note's name). */
  const start = (query: string) => {
    setOpen(true);
    setText(query);
    if (query.length >= 2) void search(query);
  };

  const approve = async (
    target: BacklinkSearchTarget,
    group: MentionGroup,
    mention: MentionSpan,
  ) => {
    setLinking(hitKey(target, group, mention));
    try {
      await api.vaultLinkMention({
        source_path: group.path,
        target_path: target.path,
        line: mention.line,
        start: mention.start,
        end: mention.end,
      });
      setResults((previous) => withoutCandidate(previous, target, group, mention));
      await onLinked(target, group);
      flash(`Linked ${target.title} in ${group.title}.`);
    } catch (e) {
      flash(String((e as Error).message ?? e));
    } finally {
      setLinking(null);
    }
  };

  return { open, setOpen, text, setText, results, searching, linking, search, start, approve };
}

export function BacklinkReviewDialog({
  review,
  onOpenNote,
}: {
  review: ReturnType<typeof useBacklinkReview>;
  onOpenNote: (path: string) => void;
}) {
  const { open, setOpen, text, setText, results, searching, linking, search, approve } = review;
  if (!open) return null;
  return (
    <div className="organizer-backdrop">
      <div className="organizer-modal backlink-review-modal card">
        <div className="row">
          <div>
            <h2 className="page-title">Search unlinked mentions</h2>
            <p className="page-sub">
              Find plain-text mentions of a note title and approve each wikilink.
            </p>
          </div>
          <div className="grow" />
          <button onClick={() => setOpen(false)}>Close</button>
        </div>
        <form
          className="backlink-search-row"
          onSubmit={(event) => {
            event.preventDefault();
            void search();
          }}
        >
          <input
            autoFocus
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Search a note title, e.g. A* Search"
          />
          <button
            className="primary"
            disabled={searching || text.trim().length < 2}
          >
            {searching ? "Searching..." : "Search"}
          </button>
        </form>
        <div className="backlink-review-results">
          {!results && (
            <div className="note-banner">
              Search for a concept or note title to review possible backlinks.
            </div>
          )}
          {results && results.targets.length === 0 && (
            <div className="note-banner">
              No unlinked mentions found for "{results.query}".
            </div>
          )}
          {results && results.targets.length > 0 && (
            <>
              <div className="small muted backlink-review-summary">
                {results.mentions} unlinked mentions across{" "}
                {results.count} target notes.
              </div>
              {results.targets.map((target) => (
                <section className="backlink-target" key={target.path}>
                  <div className="backlink-target-header">
                    <button
                      className="linked-note backlink-target-title"
                      onClick={() => onOpenNote(target.path)}
                    >
                      {target.title}
                    </button>
                    <span className="muted small">{target.path}</span>
                    <span className="pill">{target.count}</span>
                  </div>
                  {target.unlinked.map((group) => (
                    <div className="mention-group" key={`${target.path}:${group.path}`}>
                      <button
                        className="toc-item mention-title"
                        onClick={() => onOpenNote(group.path)}
                      >
                        {group.title}
                      </button>
                      {group.mentions.map((mention) => {
                        const key = hitKey(target, group, mention);
                        return (
                          <div
                            key={key}
                            className="mention-snippet mention-unlinked backlink-review-hit"
                          >
                            <span onClick={() => onOpenNote(group.path)}>
                              {mention.snippet.slice(0, mention.hl_start)}
                              <mark>
                                {mention.snippet.slice(mention.hl_start, mention.hl_end)}
                              </mark>
                              {mention.snippet.slice(mention.hl_end)}
                            </span>
                            <button
                              className="mention-link-btn"
                              disabled={linking === key}
                              onClick={() => void approve(target, group, mention)}
                            >
                              {linking === key ? "Linking..." : "Approve"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </section>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
