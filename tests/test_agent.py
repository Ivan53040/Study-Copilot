"""Phase 3 tests: context building, citation validation, grounded agent."""

from __future__ import annotations

import pytest

from app.agent.context import build_context
from app.agent.study_agent import answer
from app.agent.validation import validate_answer
from app.ingestion.service import ingest
from app.models.chat import EchoChatAdapter
from app.retrieval.indexing import index_embeddings
from app.retrieval.service import SearchResponse
from app.retrieval.types import SearchHit


def _hit(cid, content="some content", trust=5) -> SearchHit:
    return SearchHit(
        chunk_id=cid, document_id=cid, content=content, heading="H",
        page_number=None, course="REIT6811", week=1, source_type="user-note",
        trust_level=trust, title=f"Doc{cid}", path=f"/v/Doc{cid}.md",
        score=1.0, retrieval="hybrid",
    )


# ---- context builder ----

def test_build_context_numbers_sources():
    ctx = build_context([_hit(1), _hit(2)])
    assert set(ctx.sources) == {"S1", "S2"}
    assert "[S1]" in ctx.text and "[S2]" in ctx.text


def test_build_context_budget_truncates():
    hits = [_hit(i, content="x" * 1000) for i in range(10)]
    ctx = build_context(hits, max_chars=2500)
    assert 0 < len(ctx.sources) < 10  # stopped early, but kept at least one


# ---- citation validation ----

def test_validate_extracts_valid_and_invalid():
    sources = {"S1": _hit(1)}
    check = validate_answer("Reliability is consistency [S1]. Also [S5].", sources)
    assert check.cited_ids == ["S1", "S5"]
    assert len(check.valid_citations) == 1
    assert check.invalid_ids == ["S5"]
    assert any("unknown sources" in w for w in check.warnings)


def test_validate_refusal_has_no_citation_warning():
    check = validate_answer("I don't have that in your materials.", {})
    assert check.is_refusal
    assert check.ok  # refusals are allowed to have no citations


def test_validate_requires_citation_when_configured():
    check = validate_answer("Some unsupported claim.", {"S1": _hit(1)})
    assert any("without citing" in w for w in check.warnings)


# ---- grounded agent (offline via EchoChatAdapter + hash embeddings) ----

@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def test_agent_answers_with_citation(indexed):
    res = answer(
        "What is reliability?", settings=indexed, adapter=EchoChatAdapter()
    )
    assert res.conversation_id
    assert "[S1]" in res.answer
    assert res.citations  # at least one validated citation
    assert res.sources


def test_agent_persists_conversation(indexed):
    res = answer("reliability", settings=indexed, adapter=EchoChatAdapter())
    from app.database.db import session_scope
    from app.database.models import Message

    with session_scope(indexed) as s:
        msgs = (
            s.query(Message)
            .filter(Message.conversation_id == res.conversation_id)
            .all()
        )
    roles = [m.role for m in msgs]
    assert roles == ["user", "assistant"]


def test_agent_followup_reuses_conversation(indexed):
    first = answer("reliability", settings=indexed, adapter=EchoChatAdapter())
    second = answer(
        "and validity?",
        settings=indexed,
        adapter=EchoChatAdapter(),
        conversation_id=first.conversation_id,
    )
    assert second.conversation_id == first.conversation_id

    from app.database.db import session_scope
    from app.database.models import Message

    with session_scope(indexed) as s:
        count = (
            s.query(Message)
            .filter(Message.conversation_id == first.conversation_id)
            .count()
        )
    assert count == 4  # 2 user + 2 assistant


def test_agent_no_sources_declines(settings, db):
    # No vector (unreachable endpoint) + gibberish query -> empty context.
    settings.embeddings.provider = "lmstudio"
    settings.embeddings.base_url = "http://127.0.0.1:9/v1"
    ingest(settings)
    res = answer(
        "zzz qqq xyzzy nonexistentterm",
        settings=settings,
        adapter=EchoChatAdapter(),
    )
    assert res.answer == "I don't have that in your materials."


def test_scoped_agent_also_searches_lecture_materials(settings, db, monkeypatch):
    lecture_root = settings.vault.root / "Lecture Materials"
    lecture_root.mkdir()
    lecture_hit = _hit(99, content="Affordances provide clues about interaction.")
    lecture_hit.path = str(lecture_root / "DECO7250 Lecture 1.pptx")
    lecture_hit.course = "DECO7250"
    lecture_hit.source_type = "lecture-source"
    lecture_hit.trust_level = 1

    def fake_search(query, *, settings, flt, final_limit=None):
        if flt.path_prefix and "Lecture Materials" in flt.path_prefix:
            return SearchResponse(query=query, hits=[lecture_hit], used_vector=False)
        return SearchResponse(query=query, hits=[], used_vector=False)

    monkeypatch.setattr("app.agent.study_agent.search", fake_search)
    result = answer(
        "What are affordances?",
        settings=settings,
        adapter=EchoChatAdapter(),
        course="DECO7250",
    )

    assert result.sources
    assert result.sources[0]["source_type"] == "lecture-source"
