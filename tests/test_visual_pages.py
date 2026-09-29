"""Visual pages remain searchable and grounded in their original page image."""

from __future__ import annotations

import fitz
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agent.study_agent import answer
from app.api.search import get_source_page
from app.database.db import session_scope
from app.database.models import Chunk, Document
from app.ingestion.service import ingest_single_file
from app.ingestion.visual_pages import index_visual_pages
from app.models.chat import ChatError, ChatResponse
from app.retrieval.service import search
from evals.page_benchmark import run_page_benchmark


class VisionAdapter:
    model_name = "vision-test"

    def __init__(self):
        self.saw_images = 0

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        parts = [m.content for m in messages if isinstance(m.content, list)]
        assert parts
        image = next(p for p in parts[-1] if p["type"] == "image_url")
        assert image["image_url"]["url"].startswith("data:image/png;base64,")
        self.saw_images += 1
        text = " ".join(
            p["text"] for p in parts[-1] if p["type"] == "text"
        )
        if "Describe this lecture page" in text:
            return ChatResponse(
                content="red-black tree rotation diagram showing a left rotation",
                model=self.model_name,
            )
        return ChatResponse(content="The diagram shows a left rotation. [S1]", model=self.model_name)


class TextOnlyAdapter:
    model_name = "text-only"

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        if isinstance(messages[-1].content, list):
            raise ChatError("Image input unsupported")
        return ChatResponse(content="The page description mentions rotation. [S1]", model=self.model_name)


def test_image_only_page_is_retrieved_and_shown_to_answer_model(settings, db):
    settings.embeddings.provider = "hash"
    settings.generation.include_page_images = True
    source = settings.vault.root / "REIT6811 - Research Methods" / "tree.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.draw_circle(fitz.Point(100, 100), 25)
        page.draw_circle(fitz.Point(180, 150), 25)
        pdf.save(source)

    assert ingest_single_file(source, settings).chunks == 0
    with session_scope(settings) as session:
        doc_id = session.scalar(select(Document.id).where(Document.path == str(source)))

    vision = VisionAdapter()
    first = index_visual_pages(settings, vision, document_id=doc_id)
    assert first.indexed == 1 and first.errors == []
    second = index_visual_pages(settings, vision, document_id=doc_id)
    assert second.indexed == 0 and second.skipped == 1

    hits = search("red-black tree rotation", settings=settings).hits
    assert hits and hits[0].kind == "visual_page"
    assert hits[0].page_number == 1
    benchmark = run_page_benchmark({"queries": [{
        "id": "rotation", "query": "red-black tree rotation",
        "relevant_pages": [{
            "path": source.relative_to(settings.vault.root).as_posix(),
            "page": 1,
            "grade": 2,
        }],
    }]}, settings=settings, k=1)
    assert benchmark["recall"] == benchmark["ndcg"] == 1
    result = answer("Why rotate this tree?", settings=settings, adapter=vision)
    assert "[S1]" in result.answer
    assert result.citations[0]["document_id"] == doc_id
    assert result.citations[0]["page_number"] == 1
    assert vision.saw_images == 2  # indexing and grounded answer

    fallback = answer("Why rotate this tree?", settings=settings, adapter=TextOnlyAdapter())
    assert "[S1]" in fallback.answer
    assert any("Visual model unavailable" in warning for warning in fallback.warnings)

    preview = get_source_page(doc_id, 1, settings)
    assert preview.media_type == "image/png"
    assert preview.body.startswith(b"\x89PNG")
    with pytest.raises(HTTPException) as error:
        get_source_page(doc_id, 2, settings)
    assert error.value.status_code == 404

    with session_scope(settings) as session:
        chunks = session.scalars(select(Chunk).where(Chunk.document_id == doc_id)).all()
        assert len(chunks) == 1
        assert chunks[0].extra["kind"] == "visual_page"
