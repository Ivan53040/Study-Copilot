"""Phase 2 retrieval tests: keyword, vector, hybrid fusion, citations."""

from __future__ import annotations

import pytest

from app.database.db import session_scope
from app.ingestion.service import ingest
from app.models.embeddings import HashingEmbeddings
from app.retrieval.citations import format_citation, obsidian_link
from app.retrieval.hybrid_search import fuse, reciprocal_rank_fusion
from app.retrieval.indexing import index_embeddings
from app.retrieval.keyword_search import build_match_query, keyword_search
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter, SearchHit
from app.retrieval.vector_search import vector_search


def _hit(cid, trust=5, title="Doc", path="/v/Doc.md") -> SearchHit:
    return SearchHit(
        chunk_id=cid, document_id=cid, content="c", heading="H", page_number=None,
        course="REIT6811", week=1, source_type="user-note", trust_level=trust,
        title=title, path=path, score=0.0, retrieval="keyword",
    )


# ---- query sanitisation ----

def test_build_match_query_strips_punctuation():
    assert build_match_query("reliability & validity!") == '"reliability" OR "validity"'


def test_build_match_query_empty():
    assert build_match_query("?? !!") == ""


# ---- keyword search (FTS5) ----

def test_keyword_search_finds_content(settings, db):
    ingest(settings)
    with session_scope(settings) as s:
        hits = keyword_search(s, "reliability", limit=5)
    assert hits
    assert any("Reliability" in h.content or h.heading == "Reliability" for h in hits)


def test_keyword_search_metadata_filter(settings, db):
    ingest(settings)
    with session_scope(settings) as s:
        hits = keyword_search(
            s, "reliability", flt=MetadataFilter(course="REIT6811"), limit=5
        )
        none = keyword_search(
            s, "reliability", flt=MetadataFilter(course="NOPE9999"), limit=5
        )
    assert hits and not none


# ---- vector search (offline hash embeddings) ----

def test_vector_search_returns_hits(settings, db):
    ingest(settings)
    prov = HashingEmbeddings(dim=128)
    index_embeddings(settings, provider=prov)
    qv = prov.embed(["reliability of measurement"])[0]
    with session_scope(settings) as s:
        hits = vector_search(s, qv, model=prov.model_name, limit=5)
    assert hits
    assert all(h.retrieval == "vector" for h in hits)


# ---- hybrid fusion ----

def test_rrf_combines_ranks():
    a = [_hit(1), _hit(2)]
    b = [_hit(2), _hit(3)]
    scores, _ = reciprocal_rank_fusion([a, b], rrf_k=60)
    # chunk 2 appears in both lists -> highest combined score.
    assert scores[2] > scores[1] and scores[2] > scores[3]


def test_fuse_prefers_more_trusted_on_tie():
    # Same single-list rank, different trust -> trusted one ranks first.
    trusted = [_hit(1, trust=1)]
    untrusted = [_hit(2, trust=8)]
    fused = fuse(trusted + untrusted, [], trust_weight=0.15, final_limit=2)
    assert fused[0].chunk_id == 1
    assert all(h.retrieval == "hybrid" for h in fused)


# ---- end-to-end search service (graceful, offline) ----

def test_search_service_hybrid_offline(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    resp = search("reliability and validity", settings=settings)
    assert resp.used_vector is True
    assert resp.hits
    assert all(h.retrieval == "hybrid" for h in resp.hits)


def test_search_service_keyword_only_when_embeddings_fail(settings, db):
    # Point at an unreachable embedding endpoint -> must fall back gracefully.
    settings.embeddings.provider = "lmstudio"
    settings.embeddings.base_url = "http://127.0.0.1:9/v1"
    ingest(settings)
    resp = search("reliability", settings=settings)
    assert resp.used_vector is False
    assert resp.note and "keyword-only" in resp.note
    assert resp.hits  # keyword results still returned


# ---- citations ----

def test_citation_uses_obsidian_link_and_no_invented_page():
    h = _hit(1, path="/vault/REIT6811 Week 1.md")
    assert obsidian_link(h) == "[[REIT6811 Week 1]]"
    cit = format_citation(h)
    # heading present, no page -> location is the section, never a fake page.
    assert cit["location"] == "Section: H"
    assert cit["link"] == "[[REIT6811 Week 1]]"
