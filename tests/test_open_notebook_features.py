"""Regression tests for Open Notebook-inspired local features."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent.study_agent import answer
from app.config.settings import TaskModelOverride
from app.database.db import init_db, session_scope
from app.database.models import Document, Job
from app.ingestion.chunker import chunk_markdown
from app.ingestion.markdown_parser import MarkdownDocument, _split_sections
from app.ingestion.service import ingest
from app.models.chat import (
    EchoChatAdapter,
    LMStudioChatAdapter,
    OpenAIChatAdapter,
    get_chat_adapter,
)
from app.study_sets.service import metadata_filter_for_scope, save_study_set


def _md(body: str) -> MarkdownDocument:
    return MarkdownDocument(
        path=None,
        frontmatter={},
        body=body,
        sections=_split_sections(body),
    )


def test_study_set_resolves_document_filter(settings, db):
    report = ingest(settings)
    assert report.new

    with session_scope(settings) as session:
        doc = session.query(Document).filter(Document.title.like("%Revision%")).one()
        doc_id = doc.id
    saved = save_study_set(
        settings=settings,
        name="Reliability pack",
        course="REIT6811",
        items=[{"kind": "document", "ref": doc_id, "mode": "snippets"}],
    )
    set_id = saved["id"]

    flt, resolved = metadata_filter_for_scope(settings=settings, study_set_id=set_id)
    assert flt.course == "REIT6811"
    assert flt.document_ids == [doc_id]
    assert resolved.context_items == [
        {"kind": "document", "ref": doc_id, "mode": "snippets"}
    ]


def test_manual_chat_context_uses_selected_document(settings, db):
    ingest(settings)
    with session_scope(settings) as session:
        doc = session.query(Document).filter(Document.title.like("%Revision%")).one()

    result = answer(
        "What does the selected document say?",
        settings=settings,
        adapter=EchoChatAdapter(),
        context_mode="manual",
        context_items=[{"kind": "document", "ref": doc.id, "mode": "snippets"}],
    )

    assert result.sources
    assert result.sources[0]["retrieval"] == "manual"
    assert result.used_vector is False
    assert result.citations


def test_task_model_override_takes_precedence(tmp_path):
    from app.config.settings import Settings, VaultConfig

    settings = Settings(vault=VaultConfig(root=tmp_path))
    settings.models.default_provider = "lmstudio"
    settings.task_models.chat = TaskModelOverride(provider="echo")
    settings.task_models.deep_ask = TaskModelOverride(
        provider="openai", model="gpt-test", base_url="https://example.test/v1"
    )

    assert isinstance(get_chat_adapter(settings, task="chat"), EchoChatAdapter)
    deep_adapter = get_chat_adapter(settings, task="deep_ask")
    assert isinstance(deep_adapter, OpenAIChatAdapter)
    assert deep_adapter.model_name == "gpt-test"
    assert isinstance(get_chat_adapter(settings, task="transformations"), LMStudioChatAdapter)


def test_init_db_marks_stale_running_jobs_failed(settings, db):
    with session_scope(settings) as session:
        session.add(
            Job(
                type="deep_ask",
                status="running",
                started_at=datetime.now(timezone.utc),
                payload={"question": "stale"},
            )
        )

    init_db(settings)

    with session_scope(settings) as session:
        job = session.query(Job).one()
        assert job.status == "failed"
        assert "restarted" in (job.error or "").lower()


def test_token_chunking_uses_minimum_token_threshold(settings):
    settings.ingestion.chunk_tokens = 20
    settings.ingestion.chunk_overlap_tokens = 0
    settings.ingestion.min_chunk_tokens = 4

    chunks = chunk_markdown(_md("# Tiny\n\nok\n\n# Useful\n\n" + "word " * 30), settings=settings)

    assert len(chunks) >= 1
    assert all(chunk.heading != "Tiny" for chunk in chunks)
    assert chunks[0].heading == "Useful"
