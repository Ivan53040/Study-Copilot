"""AI document formatting tests."""

from app.models.chat import ChatResponse
from app.vault.formatter import preview_document_format


class StubFormatter:
    model_name = "formatter-test"

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        assert messages[-1].content.endswith("# rough title\nitem one\nitem two\n")
        assert temperature == 0.05
        return ChatResponse(
            content="# Rough title\n\n- item one\n- item two",
            model=self.model_name,
        )


def test_format_preview_preserves_frontmatter_and_newline(settings):
    raw = (
        "---\n"
        "title: Keep this exact title\n"
        "course: REIT6811\n"
        "---\n"
        "# rough title\n"
        "item one\n"
        "item two\n"
    )

    result = preview_document_format(
        "REIT6811 - Research Methods/REIT6811_Week1_Revision_Notes.md",
        raw,
        settings,
        StubFormatter(),
    )

    assert result["before"] == raw
    assert result["after"] == (
        "---\n"
        "title: Keep this exact title\n"
        "course: REIT6811\n"
        "---\n"
        "# Rough title\n\n"
        "- item one\n"
        "- item two\n"
    )
    assert result["changed"] is True
    assert result["model"] == "formatter-test"
