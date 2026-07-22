"""Deep Ask: plan several searches, answer, then synthesize."""

from __future__ import annotations

from app.agent.context import build_context
from app.agent.validation import validate_answer
from app.config.settings import Settings
from app.generation.jsonparse import extract_json
from app.jobs.service import submit_job, update_progress
from app.models.chat import ChatError, ChatMessage, get_chat_adapter
from app.retrieval.service import search
from app.retrieval.types import SearchHit
from app.study_sets.service import metadata_filter_for_scope


def submit_deep_ask(
    *,
    settings: Settings,
    question: str,
    course: str | None = None,
    scope_path: str | None = None,
    study_set_id: int | None = None,
    max_searches: int = 4,
) -> dict:
    if not question.strip():
        raise ValueError("Question is required.")
    return submit_job(
        "deep_ask",
        {
            "question": question,
            "course": course,
            "scope_path": scope_path,
            "study_set_id": study_set_id,
            "max_searches": max(1, min(6, int(max_searches or 4))),
        },
        settings,
    )


def run_deep_ask_job(payload: dict, settings: Settings, job_id: int) -> dict:
    question = str(payload.get("question", "")).strip()
    max_searches = max(1, min(6, int(payload.get("max_searches") or 4)))
    flt, _ = metadata_filter_for_scope(
        settings=settings,
        study_set_id=payload.get("study_set_id"),
        course=payload.get("course"),
        scope_path=payload.get("scope_path"),
    )

    update_progress(job_id, settings=settings, current=0, total=4, message="Planning searches...")
    adapter = get_chat_adapter(settings, task="deep_ask")
    terms = _search_terms(question, adapter, max_searches)

    update_progress(job_id, settings=settings, current=1, total=4, message="Searching sources...")
    by_chunk: dict[int, SearchHit] = {}
    per_search: list[dict] = []
    for term in terms:
        resp = search(term, settings=settings, flt=flt, final_limit=8)
        for hit in resp.hits:
            by_chunk.setdefault(hit.chunk_id, hit)
        per_search.append(
            {
                "term": term,
                "count": len(resp.hits),
                "used_vector": resp.used_vector,
            }
        )
    hits = list(by_chunk.values())[: max(8, settings.retrieval.final_context_limit * 2)]
    context = build_context(hits, max_chars=max(5000, settings.retrieval.final_context_limit * 1400))
    if context.is_empty:
        return {
            "answer": "I don't have that in your materials.",
            "citations": [],
            "sources": [],
            "warnings": ["No relevant sources found."],
            "searches": per_search,
            "model": adapter.model_name,
        }

    update_progress(job_id, settings=settings, current=2, total=4, message="Drafting partial answers...")
    partials = _partials(question, terms, context.text, adapter, settings)

    update_progress(job_id, settings=settings, current=3, total=4, message="Synthesizing final answer...")
    final = _final_answer(question, partials, context.text, adapter, settings)
    check = validate_answer(
        final,
        context.sources,
        require_citations=settings.generation.require_citations,
    )
    update_progress(job_id, settings=settings, current=4, total=4, message="Deep answer complete.")
    return {
        "answer": final,
        "citations": check.valid_citations,
        "sources": [
            {**hit.as_dict(include_content=False), "marker": sid}
            for sid, hit in context.sources.items()
        ],
        "warnings": check.warnings,
        "searches": per_search,
        "model": adapter.model_name,
    }


def _search_terms(question: str, adapter, max_searches: int) -> list[str]:
    try:
        response = adapter.generate(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Return STRICT JSON only: {\"searches\":[\"term\"]}. "
                        "Write short search terms for a study-material search engine."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=f"Question: {question}\nReturn up to {max_searches} searches.",
                ),
            ],
            temperature=0.0,
        )
        data = extract_json(response.content)
        raw = data.get("searches", [])
        terms = [str(item).strip() for item in raw if str(item).strip()]
    except (ChatError, ValueError, AttributeError):
        terms = []
    if question not in terms:
        terms.insert(0, question)
    return terms[:max_searches]


def _partials(question: str, terms: list[str], context: str, adapter, settings: Settings) -> str:
    try:
        response = adapter.generate(
            [
                ChatMessage(
                    role="system",
                    content="Answer using only SOURCES. Cite claims with [S#].",
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"SOURCES:\n{context}\n\n"
                        f"QUESTION: {question}\n"
                        f"SEARCH ANGLES: {', '.join(terms)}\n\n"
                        "Write concise findings for each angle."
                    ),
                ),
            ],
            temperature=settings.generation.temperature,
        )
        return response.content.strip()
    except ChatError:
        return ""


def _final_answer(question: str, partials: str, context: str, adapter, settings: Settings) -> str:
    response = adapter.generate(
        [
            ChatMessage(
                role="system",
                content=(
                    "You synthesize study answers from provided findings and SOURCES. "
                    "Use only the source-backed material and cite with [S#]."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"SOURCES:\n{context}\n\n"
                    f"QUESTION: {question}\n\n"
                    f"PARTIAL FINDINGS:\n{partials}\n\n"
                    "Write the final answer with citations."
                ),
            ),
        ],
        temperature=settings.generation.temperature,
    )
    return response.content.strip()
