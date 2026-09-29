// Right-hand panel: the note's headings ("On this page") and its linked and
// unlinked mentions, with a one-click "Link" for unlinked ones.

import type { MentionGroup, MentionSpan, NoteMentions, VaultNote } from "../../types";

function Snippet({ mention }: { mention: MentionSpan }) {
  return (
    <>
      {mention.snippet.slice(0, mention.hl_start)}
      <mark>{mention.snippet.slice(mention.hl_start, mention.hl_end)}</mark>
      {mention.snippet.slice(mention.hl_end)}
    </>
  );
}

const count = (groups: MentionGroup[]) => groups.reduce((n, g) => n + g.mentions.length, 0);

export function OutlinePanel({
  open,
  width,
  note,
  mentions,
  onOpen,
  onLinkMention,
}: {
  open: boolean;
  width: number;
  note: VaultNote | null;
  mentions: NoteMentions | null;
  onOpen: (path: string, newTab: boolean) => void;
  onLinkMention: (group: MentionGroup, mention: MentionSpan) => void;
}) {
  return (
    <div className="ws-toc" style={{ width: open ? width : 0 }}>
      <div className="ws-toc-inner" style={{ width }}>
        {note && note.headings.length > 0 && (
          <>
            <div className="small muted" style={{ marginBottom: 6 }}>On this page</div>
            {note.headings.map((h, i) => (
              <a
                key={i}
                className="toc-item"
                href={`#${h.slug}`}
                style={{ paddingLeft: (h.level - 1) * 10 }}
              >
                {h.text}
              </a>
            ))}
          </>
        )}
        {note && mentions && mentions.linked.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="small muted" style={{ marginBottom: 6 }}>
              Linked mentions (
              {count(mentions.linked)})
            </div>
            {mentions.linked.map((group) => (
              <div key={group.path} className="mention-group">
                <div
                  className="toc-item mention-title"
                  onClick={(e) => onOpen(group.path, e.ctrlKey || e.metaKey)}
                >
                  {group.title}
                </div>
                {group.mentions.map((m, i) => (
                  <div
                    key={i}
                    className="mention-snippet"
                    onClick={(e) => onOpen(group.path, e.ctrlKey || e.metaKey)}
                  >
                    <Snippet mention={m} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
        {note && mentions && mentions.unlinked.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="small muted" style={{ marginBottom: 6 }}>
              Unlinked mentions (
              {count(mentions.unlinked)})
            </div>
            {mentions.unlinked.map((group) => (
              <div key={group.path} className="mention-group">
                <div
                  className="toc-item mention-title"
                  onClick={(e) => onOpen(group.path, e.ctrlKey || e.metaKey)}
                >
                  {group.title}
                </div>
                {group.mentions.map((m, i) => (
                  <div key={i} className="mention-snippet mention-unlinked">
                    <span onClick={(e) => onOpen(group.path, e.ctrlKey || e.metaKey)}>
                      <Snippet mention={m} />
                    </span>
                    <button
                      className="mention-link-btn"
                      title={`Turn into a [[${mentions.name}]] link`}
                      onClick={() => onLinkMention(group, m)}
                    >
                      Link
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
