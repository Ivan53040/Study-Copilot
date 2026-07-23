"""Phase 4 tests: templates, safe writer, and revision-note generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.generation.revision_notes import generate_revision_note
from app.generation.translation import (
    translate_batch_english_to_traditional_chinese,
    translate_english_to_traditional_chinese,
)
from app.ingestion.service import ingest
from app.main import app
from app.models.chat import ChatError, ChatMessage, ChatResponse, EchoChatAdapter
from app.obsidian.templates import (
    render_revision_note,
    revision_note_frontmatter,
)
from app.obsidian.writer import safe_filename, write_note
from app.retrieval.indexing import index_embeddings
from app.security.paths import PathSecurityError


# ---- templates ----

def test_frontmatter_marks_ai_generated():
    fm = revision_note_frontmatter(
        title="REIT6811 Week 1 Revision Notes",
        course="REIT6811",
        week=1,
        derived_from=["[[Week 1]]"],
    )
    assert fm["type"] == "revision-note"
    assert fm["source_type"] == "ai-generated"
    assert fm["reviewed_by_user"] is False
    assert fm["derived_from"] == ["[[Week 1]]"]


def test_render_note_has_banner_and_sources():
    fm = revision_note_frontmatter(
        title="T", course="REIT6811", week=1, derived_from=[]
    )
    out = render_revision_note(
        frontmatter=fm, body="## Concept\n- point [S1]", sources_section="## Sources\n- [S1] [[x]]"
    )
    assert out.startswith("---")
    assert "AI-generated revision note" in out
    assert "## Sources" in out


# ---- safe writer ----

def test_safe_filename_strips_invalid():
    assert safe_filename('a/b:c?"*.md') == "a b c .md"


def test_writer_allows_inside_studycopilot(settings, db):
    rel = "StudyCopilot/Generated Notes/test.md"
    res = write_note(rel, "hello", settings)
    assert res.written
    assert (settings.output_root / "Generated Notes" / "test.md").exists()


def test_writer_blocks_outside_studycopilot(settings, db):
    with pytest.raises(PathSecurityError):
        write_note("REIT6811 - Research Methods/hack.md", "x", settings)


# ---- generation ----

@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def test_generate_preview_does_not_write(indexed):
    preview = generate_revision_note(
        course="REIT6811", week=1, settings=indexed,
        adapter=EchoChatAdapter(), write=False,
    )
    assert preview.content.startswith("---")  # has frontmatter
    assert "source_type: ai-generated" in preview.content
    assert "## Sources" in preview.content
    assert preview.sources
    assert preview.written is False
    # No file created on preview.
    out_dir = indexed.output_root / "Generated Notes"
    assert not out_dir.exists() or not list(out_dir.glob("*.md"))


def test_generate_write_creates_file_in_studycopilot(indexed):
    preview = generate_revision_note(
        course="REIT6811", week=1, settings=indexed,
        adapter=EchoChatAdapter(), write=True,
    )
    assert preview.written
    written = Path(preview.target_path)
    assert written.exists()
    # Must be inside StudyCopilot/.
    assert indexed.output_root.resolve() in written.resolve().parents
    text = written.read_text(encoding="utf-8")
    assert "type: revision-note" in text and "## Sources" in text


def test_generate_no_sources_warns(settings, db):
    settings.embeddings.provider = "lmstudio"
    settings.embeddings.base_url = "http://127.0.0.1:9/v1"
    ingest(settings)
    preview = generate_revision_note(
        course="NOPE9999", settings=settings, adapter=EchoChatAdapter()
    )
    assert preview.content == ""
    assert any("No sources" in w for w in preview.warnings)
    assert preview.written is False


# ---- translation ----


class _FakeTranslationAdapter:
    model_name = "fake-local"

    def __init__(self, content="可靠性", fail=False):
        self.content = content
        self.fail = fail
        self.calls = []

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self.fail:
            raise ChatError("connection refused")
        return ChatResponse(content=self.content, model=self.model_name)


def test_translate_uses_local_adapter_contract(settings):
    adapter = _FakeTranslationAdapter()
    result = translate_english_to_traditional_chinese(
        "Reliability",
        settings=settings,
        adapter=adapter,
    )

    assert result.translation == "可靠性"
    assert result.source_language == "English"
    assert result.target_language == "Traditional Chinese"
    assert result.model == "fake-local"
    assert "/no_think" in adapter.calls[0]["messages"][0].content
    assert "/no_think" in adapter.calls[0]["messages"][1].content
    assert "Traditional Chinese" in adapter.calls[0]["messages"][0].content
    assert "Reliability" in adapter.calls[0]["messages"][1].content


def test_translate_rejects_empty_text(settings):
    with pytest.raises(ValueError):
        translate_english_to_traditional_chinese("   ", settings=settings)


def test_translate_rejects_overlong_text(settings):
    with pytest.raises(ValueError):
        translate_english_to_traditional_chinese("a" * 4001, settings=settings)


def test_translate_surfaces_local_llm_failure(settings):
    with pytest.raises(ChatError):
        translate_english_to_traditional_chinese(
            "Reliability",
            settings=settings,
            adapter=_FakeTranslationAdapter(fail=True),
        )


def test_translate_endpoint_returns_fixed_language_pair(settings, monkeypatch):
    class FakeLMStudio:
        def __init__(self, base_url, model, **kwargs):
            assert base_url == settings.models.lmstudio.base_url
            assert model == settings.models.lmstudio.model

        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            return ChatResponse(content="可靠性", model="local-test")

    monkeypatch.setattr("app.generation.translation.LMStudioChatAdapter", FakeLMStudio)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        res = TestClient(app).post("/notes/translate", json={"text": "Reliability"})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["text"] == "Reliability"
    assert data["translation"] == "可靠性"
    assert data["source_language"] == "English"
    assert data["target_language"] == "Traditional Chinese"
    assert data["model"] == "local-test"


def test_translate_endpoint_rejects_empty_text(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        res = TestClient(app).post("/notes/translate", json={"text": ""})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 422


def test_translate_endpoint_maps_local_llm_failure(settings, monkeypatch):
    class BrokenLMStudio:
        def __init__(self, base_url, model, **kwargs):
            pass

        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            raise ChatError("connection refused")

    monkeypatch.setattr("app.generation.translation.LMStudioChatAdapter", BrokenLMStudio)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        res = TestClient(app).post("/notes/translate", json={"text": "Reliability"})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 502
    assert "Local LLM translation failed" in res.json()["detail"]


def test_translate_batch_returns_ordered_translations(settings):
    adapter = _FakeTranslationAdapter(content='["第一週", "自然語言處理"]')
    result = translate_batch_english_to_traditional_chinese(
        ["Week 1", "Natural language processing"],
        settings=settings,
        adapter=adapter,
    )

    assert result.translations == ["第一週", "自然語言處理"]
    assert result.source_language == "English"
    assert result.target_language == "Traditional Chinese"
    assert "JSON array" in adapter.calls[0]["messages"][1].content


def test_translate_batch_endpoint(settings, monkeypatch):
    class FakeLMStudio:
        def __init__(self, base_url, model, **kwargs):
            pass

        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            return ChatResponse(content='["第一週", "自然語言處理"]', model="local-test")

    monkeypatch.setattr("app.generation.translation.LMStudioChatAdapter", FakeLMStudio)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        res = TestClient(app).post(
            "/notes/translate-batch",
            json={"texts": ["Week 1", "Natural language processing"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["translations"] == ["第一週", "自然語言處理"]
    assert data["target_language"] == "Traditional Chinese"


def test_translate_note_endpoint_creates_sibling_note(settings, monkeypatch):
    class FakeLMStudio:
        def __init__(self, base_url, model, **kwargs):
            pass

        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            return ChatResponse(content="譯文", model="local-test")

    monkeypatch.setattr("app.generation.translation.LMStudioChatAdapter", FakeLMStudio)
    source = "REIT6811 - Research Methods/REIT6811_Week1_Revision_Notes.md"
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        res = TestClient(app).post("/notes/translate-note", json={"path": source})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["path"].endswith("(translated).md")
    written = settings.vault.root / data["path"]
    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert "translated_from" in content
    assert "譯文" in content
