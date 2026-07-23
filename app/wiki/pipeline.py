"""Two-step chain-of-thought wiki pipeline: analyze a source, then generate pages.

Step 1 (ANALYSIS) reads the source plus the current wiki index and returns a
structured survey of entities/concepts and contradictions. Step 2 (GENERATION)
turns that analysis into actual Markdown pages. Merging is merge-by-rewrite:
for existing pages the model receives the old body and returns the complete
merged page; frontmatter is always composed in code.
"""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from datetime import date

from app.config.settings import Settings
from app.models.chat import ChatError, ChatMessage
from app.generation.jsonparse import extract_json
from app.wiki import store

_ANALYSIS_SYSTEM = (
    "You maintain a wiki of interlinked study notes for a student. "
    "Return STRICT JSON only, matching the requested schema exactly. "
    "No prose outside the JSON object."
    " Create pages only for durable, reusable concepts or named entities."
    " Never create concept/entity pages for the source document itself, course"
    " codes, modules, weeks, lectures, chapters, assignments, exams, or course"
    " overviews; those belong in the source summary or course map."
)

_ANALYSIS_SCHEMA = """{
  "summary": "2-3 sentence summary of this source document",
  "entities": [
    {"name": "Page title", "type": "concept" or "entity",
     "description": "one line",
     "exists_in_wiki": true or false,
     "related_pages": ["Other page titles this should link to"]}
  ],
  "contradictions": [
    {"page": "Existing page title", "claim_in_source": "...", "conflict_with_wiki": "..."}
  ]
}"""

_GENERATION_SYSTEM = (
    "You write wiki pages for a student's study vault. "
    "Return STRICT JSON only, matching the requested schema exactly. "
    "Page bodies are Markdown and must cross-reference other wiki pages with "
    "[[wikilinks]] (double square brackets around the exact page title). "
    "Do not include YAML frontmatter in bodies; it is added automatically."
    " Each new concept/entity page must stand alone with a clear definition,"
    " meaningful explanation, and relationships to other concepts. Do not emit"
    " thin glossary stubs or pages for modules, weeks, lectures, assignments,"
    " exams, course codes, or source-document titles."
)

_GENERATION_SCHEMA = """{
  "source_page_body": "Markdown body for the source-summary page, linking to entity pages with [[wikilinks]]",
  "pages": [
    {"title": "Page title", "type": "concept" or "entity",
     "action": "create" or "update",
     "summary": "one line for the wiki index",
     "body": "Full Markdown body with [[wikilinks]]. For action=update return the COMPLETE merged page (existing content preserved, new material integrated), not a diff."}
  ]
}"""


class WikiPipelineError(RuntimeError):
    """A source could not be processed (bad JSON after retries, chat failure)."""


def _generate_json(
    adapter, system: str, user: str, settings: Settings
) -> dict:
    """One strict-JSON call with up to ``wiki.json_retries`` re-asks."""
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]
    attempts = 1 + max(0, settings.wiki.json_retries)
    last_error = "empty response"
    for _ in range(attempts):
        try:
            response = adapter.generate(messages, temperature=0.0)
        except ChatError as exc:
            raise WikiPipelineError(f"Chat model failed: {exc}") from exc
        try:
            data = extract_json(response.content)
        except ValueError:
            last_error = "model did not return valid JSON"
            messages = messages + [
                ChatMessage(role="assistant", content=response.content),
                ChatMessage(
                    role="user",
                    content="Your previous reply was not valid JSON. Return ONLY the JSON object.",
                ),
            ]
            continue
        if isinstance(data, dict):
            return data
        last_error = "model returned a JSON array, expected an object"
    raise WikiPipelineError(last_error)


def _purpose_block(course: str | None, settings: Settings) -> str:
    purpose = store.read_purpose(course, settings)
    return f"WIKI PURPOSE (set by the user):\n{purpose}\n\n" if purpose else ""


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n\n[truncated]"


def _page_title(value: object) -> str:
    """Normalize model-returned page titles; bodies still use raw wikilinks."""
    title = " ".join(str(value or "").split()).strip()
    while title.startswith("[[") and title.endswith("]]"):
        title = title[2:-2].strip()
    return title.split("|", 1)[0].strip()


def analyze_source(
    *,
    title: str,
    source_text: str,
    course: str | None,
    adapter,
    settings: Settings,
) -> dict:
    user = (
        f"{_purpose_block(course, settings)}"
        f"WIKI INDEX (current pages):\n{store.index_excerpt_for_prompt(course, settings)}\n\n"
        f"SOURCE DOCUMENT ({title}, course {course or 'unspecified'}):\n"
        f"{_clip(source_text, settings.wiki.max_source_chars)}\n\n"
        "Analyze this source for the wiki. Identify the key entities and concepts "
        "worth a wiki page, connections to existing wiki pages, and any "
        "contradictions with existing wiki knowledge.\n"
        f"Return JSON matching this schema:\n{_ANALYSIS_SCHEMA}"
    )
    data = _generate_json(adapter, _ANALYSIS_SYSTEM, user, settings)
    entities = [
        {
            "name": _page_title(e.get("name")),
            "type": "entity" if str(e.get("type", "")).lower() == "entity" else "concept",
            "description": str(e.get("description", "")).strip(),
            "exists_in_wiki": bool(e.get("exists_in_wiki")),
            "related_pages": [
                title for r in (e.get("related_pages") or [])
                if (title := _page_title(r))
            ],
        }
        for e in (data.get("entities") or [])
        if isinstance(e, dict) and _page_title(e.get("name"))
    ][: settings.wiki.max_pages_per_source]
    contradictions = [
        {
            "page": _page_title(c.get("page")),
            "claim_in_source": str(c.get("claim_in_source", "")).strip(),
            "conflict_with_wiki": str(c.get("conflict_with_wiki", "")).strip(),
        }
        for c in (data.get("contradictions") or [])
        if isinstance(c, dict) and _page_title(c.get("page"))
    ]
    return {
        "summary": str(data.get("summary", "")).strip(),
        "entities": entities,
        "contradictions": contradictions,
    }


def generate_pages(
    *,
    title: str,
    source_text: str,
    course: str | None,
    analysis: dict,
    existing_pages: dict[str, dict],
    adapter,
    settings: Settings,
) -> dict:
    existing_blocks = "\n\n".join(
        f"### {name} (current content)\n"
        f"{_clip(page['body'], settings.wiki.max_existing_page_chars)}"
        for name, page in existing_pages.items()
    )
    user = (
        f"{_purpose_block(course, settings)}"
        f"SOURCE DOCUMENT ({title}, course {course or 'unspecified'}):\n"
        f"{_clip(source_text, settings.wiki.max_source_chars)}\n\n"
        f"ANALYSIS:\n{json.dumps(analysis, ensure_ascii=False, indent=2)}\n\n"
        + (f"EXISTING PAGES (merge new material into these):\n{existing_blocks}\n\n" if existing_blocks else "")
        + "Write the wiki pages for the entities/concepts in the analysis "
        f"(at most {settings.wiki.max_pages_per_source} pages), plus a body for "
        "the source-summary page. Use action=update for pages listed under "
        "EXISTING PAGES and return their complete merged content.\n"
        f"Return JSON matching this schema:\n{_GENERATION_SCHEMA}"
    )
    data = _generate_json(adapter, _GENERATION_SYSTEM, user, settings)
    pages = [
        {
            "title": _page_title(p.get("title")),
            "type": "entity" if str(p.get("type", "")).lower() == "entity" else "concept",
            "action": "update" if str(p.get("action", "")).lower() == "update" else "create",
            "summary": str(p.get("summary", "")).strip(),
            "body": str(p.get("body", "")).strip(),
        }
        for p in (data.get("pages") or [])
        if isinstance(p, dict) and _page_title(p.get("title")) and str(p.get("body", "")).strip()
    ][: settings.wiki.max_pages_per_source]
    return {
        "source_page_body": str(data.get("source_page_body", "")).strip(),
        "pages": pages,
    }


def _page_meta(
    *,
    title: str,
    page_type: str,
    course: str | None,
    sources: list[str],
    summary: str,
) -> dict:
    return {
        "title": title,
        "type": page_type,
        "course": course,
        "sources": sources,
        "summary": summary,
        "source_type": "ai-generated",
        "reviewed_by_user": False,
        "updated_at": date.today().isoformat(),
    }


def process_source(
    *,
    title: str,
    source_ref: str,
    source_text: str,
    course: str | None,
    adapter,
    settings: Settings,
    write_lock: threading.Lock | None = None,
) -> dict:
    """Run the two-step chain for one source and write the resulting pages.

    ``source_ref`` is the vault-relative (or absolute, for external sources)
    path recorded in each page's frontmatter ``sources`` list.
    ``write_lock`` serializes the filesystem phase when several sources are
    processed in parallel; the slow LLM calls stay outside the lock.
    Raises :class:`WikiPipelineError` when the model output is unusable.
    """
    analysis = analyze_source(
        title=title, source_text=source_text, course=course,
        adapter=adapter, settings=settings,
    )

    existing_pages: dict[str, dict] = {}
    for entity in analysis["entities"]:
        page = store.find_existing_page(course, entity["name"], settings)
        if page is not None:
            existing_pages[entity["name"]] = page

    generation = generate_pages(
        title=title, source_text=source_text, course=course,
        analysis=analysis, existing_pages=existing_pages,
        adapter=adapter, settings=settings,
    )

    created: list[str] = []
    updated: list[str] = []
    written_paths: list[str] = []

    with write_lock if write_lock is not None else nullcontext():
        # Source-summary page.
        summary_rel = store.page_rel_path(course, "source", title, settings)
        source_body = generation["source_page_body"] or analysis["summary"] or "(no summary)"
        store.write_page(
            summary_rel,
            _page_meta(
                title=title, page_type="source", course=course,
                sources=[source_ref], summary=analysis["summary"],
            ),
            source_body,
            settings,
        )

        # Entity/concept pages.
        for page in generation["pages"]:
            existing = store.find_existing_page(course, page["title"], settings)
            if existing is not None:
                sources = sorted(set(existing["sources"]) | {source_ref})
                meta = _page_meta(
                    title=existing["title"],
                    page_type=existing["type"],
                    course=existing.get("course") or course,
                    sources=sources,
                    summary=page["summary"] or existing["summary"],
                )
                seen = existing_pages.get(page["title"])
                if seen is not None and seen["body"] == existing["body"]:
                    # Merge-by-rewrite: the model saw the current body and
                    # returned the complete merged page.
                    body = page["body"]
                else:
                    # The page exists but the model never saw its current
                    # body (analysis missed it, or a parallel worker updated
                    # it since) — append rather than clobber content.
                    body = (
                        f"{existing['body']}\n\n## From [[{title}]]\n\n"
                        f"{store.strip_llm_frontmatter(page['body'])}"
                    )
                store.write_page(existing["path"], meta, body, settings)
                updated.append(existing["title"])
                written_paths.append(existing["path"])
            else:
                rel = store.page_rel_path(course, page["type"], page["title"], settings)
                meta = _page_meta(
                    title=page["title"], page_type=page["type"], course=course,
                    sources=[source_ref], summary=page["summary"],
                )
                store.write_page(rel, meta, page["body"], settings)
                created.append(page["title"])
                written_paths.append(rel)

        # Contradictions become review callouts on the affected pages.
        for item in analysis["contradictions"]:
            page = store.find_existing_page(course, item["page"], settings)
            if page is None:
                continue
            callout = (
                f"\n\n> [!warning] Possible contradiction (from [[{title}]])\n"
                f"> Source claims: {item['claim_in_source']}\n"
                f"> Conflicts with: {item['conflict_with_wiki']}"
            )
            meta = _page_meta(
                title=page["title"], page_type=page["type"],
                course=page.get("course") or course,
                sources=page["sources"], summary=page["summary"],
            )
            store.write_page(page["path"], meta, page["body"] + callout, settings)

    return {
        "summary_page": summary_rel,
        "pages": written_paths,
        "created": created,
        "updated": updated,
        "contradictions": len(analysis["contradictions"]),
    }
