"""Classify a document: course, week, type, source type, trust level.

Rules of engagement (per the build plan):
  * Frontmatter, if present, always wins — we never rewrite source files,
    so an author's explicit ``source_type``/``trust_level`` is authoritative.
  * Otherwise we infer from the path and filename with transparent heuristics.
  * External sources can carry hints (course/source_type) from config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Source-type -> trust level (1 = most trusted, 8 = least). See plan §9.
TRUST_LEVELS: dict[str, int] = {
    "official-course-material": 1,
    "lecture-source": 1,
    "assignment-brief": 2,
    "rubric": 2,
    "marking-guide": 2,
    "past-paper": 3,
    "feedback": 4,
    "user-note": 5,
    "user-reviewed-ai": 6,
    "ai-generated": 7,
    "external-web": 8,
}
DEFAULT_SOURCE_TYPE = "user-note"
DEFAULT_TRUST_LEVEL = TRUST_LEVELS[DEFAULT_SOURCE_TYPE]

# Course codes like REIT6811 / DECO 7180. Underscores are word chars, so we
# can't use \b around the digits; use explicit non-alphanumeric look-arounds.
_COURSE_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3,4}\s?\d{4})(?![0-9])")
_WEEK_RE = re.compile(r"week[\s_-]?(\d{1,2})", re.IGNORECASE)


@dataclass
class Classification:
    title: str
    course: str | None
    week: int | None
    document_type: str
    source_type: str
    trust_level: int


def _normalise_course(raw: str | None) -> str | None:
    """Reduce any course label to its canonical code (e.g. ``REIT6811``).

    ``"REIT6811 - Research Methods"``, ``"REIT6811"`` and ``"reit6811"`` all
    normalise to ``REIT6811`` so they don't fragment into separate courses.
    """
    if not raw:
        return None
    m = _COURSE_CODE_RE.search(raw.upper())
    if m:
        return m.group(1).replace(" ", "")
    return raw.strip().replace(" ", "").upper() or None


def _infer_course(path: Path, hint: str | None) -> str | None:
    if hint:
        return _normalise_course(hint)
    # Search the filename first, then walk parent folders from nearest to
    # farthest. This keeps course classification working in nested structures
    # such as "Year 1 Sem 1/CSSE7030/Lectures/Week 1.md".
    for part in [path.stem, *reversed(path.parent.parts)]:
        m = _COURSE_CODE_RE.search(part.upper())
        if m:
            return _normalise_course(m.group(1))
    return None


def _infer_week(path: Path, frontmatter: dict) -> int | None:
    if isinstance(frontmatter.get("week"), int):
        return frontmatter["week"]
    m = _WEEK_RE.search(path.stem)
    if m:
        return int(m.group(1))
    return None


def _infer_document_type(name_lower: str) -> str:
    if "marking" in name_lower and "guide" in name_lower:
        return "marking-guide"
    if "mock" in name_lower and "exam" in name_lower:
        return "mock-exam"
    if "model_answer" in name_lower or "model answer" in name_lower:
        return "model-answers"
    if "past" in name_lower and ("paper" in name_lower or "exam" in name_lower):
        return "past-paper"
    if "revision" in name_lower or "notes" in name_lower:
        return "revision-note"
    if "presentation" in name_lower:
        return "presentation"
    if "plan" in name_lower:
        return "plan"
    return "note"


def _infer_source_type(document_type: str, ext: str, hint: str | None) -> str:
    if hint:
        return hint
    # PDFs of past papers/exams are official material.
    if document_type == "past-paper" or ext == ".pdf":
        return "past-paper"
    if document_type == "marking-guide":
        return "marking-guide"
    # Markdown notes the user keeps are user-notes unless told otherwise.
    return DEFAULT_SOURCE_TYPE


def _title_from(frontmatter: dict, path: Path) -> str:
    fm_title = frontmatter.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    return path.stem.replace("_", " ").strip()


def classify(
    path: str | Path,
    *,
    frontmatter: dict | None = None,
    course_hint: str | None = None,
    source_type_hint: str | None = None,
) -> Classification:
    p = Path(path)
    frontmatter = frontmatter or {}
    name_lower = p.stem.lower()
    ext = p.suffix.lower()

    title = _title_from(frontmatter, p)
    course = _normalise_course(frontmatter.get("course")) or _infer_course(
        p, course_hint
    )
    week = _infer_week(p, frontmatter)

    document_type = (
        frontmatter.get("type")
        or frontmatter.get("document_type")
        or _infer_document_type(name_lower)
    )

    source_type = (
        frontmatter.get("source_type")
        or _infer_source_type(document_type, ext, source_type_hint)
    )
    if "Lecture Materials" in p.parts and not frontmatter.get("source_type"):
        source_type = "lecture-source"
        if not frontmatter.get("type") and not frontmatter.get("document_type"):
            document_type = "presentation" if ext == ".pptx" else "lecture-material"

    fm_trust = frontmatter.get("trust_level")
    if isinstance(fm_trust, int):
        trust_level = fm_trust
    else:
        trust_level = TRUST_LEVELS.get(source_type, DEFAULT_TRUST_LEVEL)

    return Classification(
        title=title,
        course=course,
        week=week,
        document_type=document_type,
        source_type=source_type,
        trust_level=trust_level,
    )
