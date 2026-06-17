"""Parse Markdown: split frontmatter, body, and heading-based sections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# Fenced code blocks must be ignored when scanning for headings.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    heading: str | None
    level: int
    content: str
    order: int


@dataclass
class MarkdownDocument:
    path: Path
    frontmatter: dict
    body: str
    sections: list[Section] = field(default_factory=list)


def _split_sections(body: str) -> list[Section]:
    sections: list[Section] = []
    current_heading: str | None = None
    current_level = 0
    buffer: list[str] = []
    order = 0
    in_fence = False

    def flush() -> None:
        nonlocal order
        text = "\n".join(buffer).strip()
        if text or current_heading is not None:
            sections.append(
                Section(
                    heading=current_heading,
                    level=current_level,
                    content=text,
                    order=order,
                )
            )
            order += 1

    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue
        m = _HEADING_RE.match(line) if not in_fence else None
        if m:
            flush()
            buffer = []
            current_heading = m.group(2).strip()
            current_level = len(m.group(1))
        else:
            buffer.append(line)
    flush()
    return sections


def parse_markdown(path: str | Path) -> MarkdownDocument:
    p = Path(path)
    post = frontmatter.load(str(p))
    body = post.content or ""
    return MarkdownDocument(
        path=p,
        frontmatter=dict(post.metadata),
        body=body,
        sections=_split_sections(body),
    )
