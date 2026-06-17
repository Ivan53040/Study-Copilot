"""Build a numbered source-context block from search hits."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.retrieval.citations import format_citation_markdown
from app.retrieval.types import SearchHit

DEFAULT_MAX_CHARS = 6000


@dataclass
class ContextBlock:
    text: str
    # Maps citation marker ("S1") -> the hit it refers to.
    sources: dict[str, SearchHit] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.sources


def build_context(
    hits: list[SearchHit], *, max_chars: int = DEFAULT_MAX_CHARS
) -> ContextBlock:
    blocks: list[str] = []
    sources: dict[str, SearchHit] = {}
    budget = 0
    for i, hit in enumerate(hits, start=1):
        sid = f"S{i}"
        header = f"[{sid}] {format_citation_markdown(hit)} (trust {hit.trust_level})"
        body = hit.content.strip()
        block = f"{header}\n{body}"
        if blocks and budget + len(block) > max_chars:
            break
        blocks.append(block)
        sources[sid] = hit
        budget += len(block)
    return ContextBlock(text="\n\n".join(blocks), sources=sources)
