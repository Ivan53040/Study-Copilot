"""Validate the [S#] citations an answer makes against the sources it was given."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.retrieval.citations import format_citation
from app.retrieval.types import SearchHit

_SID_RE = re.compile(r"\[S(\d+)\]")
# A refusal is a valid, citation-free answer.
_REFUSAL_MARKERS = ("i don't have that in your materials", "i don't know")


@dataclass
class CitationCheck:
    cited_ids: list[str] = field(default_factory=list)
    valid_citations: list[dict] = field(default_factory=list)
    invalid_ids: list[str] = field(default_factory=list)
    is_refusal: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.warnings


def validate_answer(
    answer: str, sources: dict[str, SearchHit], *, require_citations: bool = True
) -> CitationCheck:
    check = CitationCheck()
    lowered = answer.strip().lower()
    check.is_refusal = any(m in lowered for m in _REFUSAL_MARKERS)

    seen: set[str] = set()
    for num in _SID_RE.findall(answer):
        sid = f"S{num}"
        if sid in seen:
            continue
        seen.add(sid)
        check.cited_ids.append(sid)
        hit = sources.get(sid)
        if hit is None:
            # Model cited a source that wasn't provided -> hallucinated marker.
            check.invalid_ids.append(sid)
        else:
            check.valid_citations.append(format_citation(hit))

    if check.invalid_ids:
        check.warnings.append(
            f"Answer cites unknown sources: {', '.join(check.invalid_ids)}"
        )
    if require_citations and not check.is_refusal and not check.valid_citations:
        check.warnings.append("Answer made claims without citing any source.")
    return check
