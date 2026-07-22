"""Backlinks and unlinked mentions (app/vault/links.py + /vault/backlinks)."""

from __future__ import annotations

import pytest

from app.security.paths import PathSecurityError
from app.vault.links import (
    get_mentions,
    link_mention,
    review_mentions_with_ai,
    review_wiki_backlinks,
    search_backlink_candidates,
)
from app.vault.service import read_note, rename_note

COURSE = "REIT6811 - Research Methods"


def _write(settings, name: str, text: str) -> str:
    rel = f"{COURSE}/{name}"
    (settings.vault.root / rel).write_text(text, encoding="utf-8")
    return rel


# ---- get_mentions ----

def test_linked_mentions_found_with_snippets(settings):
    target = _write(settings, "Reliability.md", "# Reliability\n")
    _write(
        settings,
        "Lecture 2.md",
        "# Lecture 2\n\nSee [[Reliability]] before the exam.\n",
    )
    result = get_mentions(target, settings)
    assert [g["title"] for g in result["linked"]] == ["Lecture 2"]
    mention = result["linked"][0]["mentions"][0]
    assert mention["line"] == 3
    assert mention["snippet"] == "See [[Reliability]] before the exam."
    assert mention["snippet"][mention["hl_start"] : mention["hl_end"]] == "[[Reliability]]"


def test_linked_mentions_match_alias_and_heading_forms(settings):
    target = _write(settings, "Validity.md", "# Validity\n")
    _write(
        settings,
        "Lecture 3.md",
        "[[Validity|construct validity]] and [[Validity#Types]].\n",
    )
    result = get_mentions(target, settings)
    assert len(result["linked"][0]["mentions"]) == 2


def test_unlinked_mentions_skip_links_code_and_frontmatter(settings):
    target = _write(settings, "Sampling.md", "# Sampling\n")
    _write(
        settings,
        "Lecture 4.md",
        "---\ntopic: Sampling\n---\n"
        "Sampling matters. Already linked: [[Sampling]].\n"
        "`Sampling` in code and [Sampling](https://x.com) don't count.\n"
        "```\nSampling inside a fence\n```\n"
        "But sampling (any case) counts, not resampling.\n",
    )
    result = get_mentions(target, settings)
    mentions = result["unlinked"][0]["mentions"]
    assert [m["line"] for m in mentions] == [4, 9]
    first = mentions[0]
    assert first["snippet"][first["hl_start"] : first["hl_end"]] == "Sampling"


def test_note_does_not_mention_itself(settings):
    target = _write(settings, "Ethics.md", "# Ethics\n\nEthics and [[Ethics]].\n")
    result = get_mentions(target, settings)
    assert result["linked"] == []
    assert result["unlinked"] == []


def test_mentions_reflect_edits_despite_cache(settings):
    target = _write(settings, "Bias.md", "# Bias\n")
    other = _write(settings, "Lecture 5.md", "Nothing here.\n")
    assert get_mentions(target, settings)["unlinked"] == []
    (settings.vault.root / other).write_text("Bias is everywhere.\n", encoding="utf-8")
    assert len(get_mentions(target, settings)["unlinked"]) == 1


def test_get_mentions_missing_note_raises(settings):
    with pytest.raises(FileNotFoundError):
        get_mentions(f"{COURSE}/Nope.md", settings)


def test_get_mentions_denied_path_raises(settings):
    with pytest.raises(PathSecurityError):
        get_mentions("../outside.md", settings)


def test_search_backlink_candidates_returns_approval_queue(settings):
    target = _write(settings, "Backlinkability.md", "# Backlinkability\n")
    source = _write(
        settings,
        "Lecture Search.md",
        "Backlinkability is repeated. Backlinkability is important.\n",
    )
    _write(settings, "Other.md", "Nothing relevant.\n")

    result = search_backlink_candidates("Backlinkability", settings)

    assert result["count"] == 1
    assert result["mentions"] == 2
    hit = result["targets"][0]
    assert hit["path"] == target
    assert hit["title"] == "Backlinkability"
    assert hit["unlinked"][0]["path"] == source
    assert [m["line"] for m in hit["unlinked"][0]["mentions"]] == [1, 1]


def test_mentions_can_use_display_title_alias(settings):
    target = _write(settings, "A Search.md", "# A* Search\n")
    source = _write(settings, "Lecture Alias.md", "A* Search uses a priority queue.\n")

    result = get_mentions(target, settings, aliases=["A* Search"])
    mention = result["unlinked"][0]["mentions"][0]
    assert mention["snippet"][mention["hl_start"] : mention["hl_end"]] == "A* Search"

    linked = link_mention(
        source,
        target,
        mention["line"],
        mention["start"],
        mention["end"],
        settings,
        aliases=["A* Search"],
    )
    assert linked["link"] == "[[A Search|A* Search]]"
    assert "[[A Search|A* Search]] uses a priority queue." in read_note(source, settings)["content"]


def test_ai_review_keeps_only_relevant_candidates(settings, monkeypatch):
    from app.models.chat import ChatResponse

    settings.vault.read_paths = ["**"]
    target = "StudyCopilot/Wiki/All Courses/Concepts/Reliability.md"
    target_path = settings.vault.root / target
    target_path.parent.mkdir(parents=True)
    target_path.write_text(
        "---\ntitle: Reliability\ntype: concept\nsummary: Measurement consistency\n---\n"
        "# Reliability\n\nReliability is consistency of measurement.\n",
        encoding="utf-8",
    )
    source = _write(
        settings,
        "AI review.md",
        "Reliability is the consistency of a measurement.\n"
        "The system reliability of the server is a separate engineering topic.\n",
    )

    class Adapter:
        model_name = "local-test"

        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            return ChatResponse(
                content='{"relevant":[{"id":"c0","reason":"measurement concept","confidence":0.96}]}',
                model=self.model_name,
            )

    monkeypatch.setattr("app.vault.links.get_chat_adapter", lambda *args, **kwargs: Adapter())
    result = review_mentions_with_ai(target, settings, aliases=["Reliability"])
    assert result["model"] == "local-test"
    assert result["candidates"] >= 2
    assert result["reviewed"] == 1
    mention = result["unlinked"][0]["mentions"][0]
    assert result["unlinked"][0]["path"] == source
    assert mention["reason"] == "measurement concept"


def test_ai_review_accepts_relevant_line_response(settings, monkeypatch):
    settings.vault.read_paths = ["**"]
    target = _write(settings, "Consistency.md", "# Consistency\n")
    _write(settings, "Line response.md", "Consistency matters in measurement.\n")

    class Adapter:
        model_name = "local-test"

        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            return type("Response", (), {"content": "RELEVANT: c0"})()

    monkeypatch.setattr("app.vault.links.get_chat_adapter", lambda *args, **kwargs: Adapter())
    result = review_mentions_with_ai(target, settings)
    assert result["reviewed"] == 1
    assert result["notice"] is None
    assert result["unlinked"][0]["mentions"][0]["reason"] == "Selected by the local model."


def test_batch_ai_review_collects_only_suggested_wiki_pages(settings, monkeypatch):
    wiki_root = settings.vault.root / "StudyCopilot/Wiki/TEST"
    (wiki_root / "Concepts").mkdir(parents=True)
    for name in ("Alpha", "Beta"):
        (wiki_root / "Concepts" / f"{name}.md").write_text(
            f"---\ntitle: {name}\ntype: concept\n---\n# {name}\n", encoding="utf-8"
        )
    (wiki_root / "Sources").mkdir()
    (wiki_root / "Sources/Skip.md").write_text(
        "---\ntitle: Skip\ntype: source\n---\n# Skip\n", encoding="utf-8"
    )

    def fake_review(path, settings, aliases=None):
        if path.endswith("Alpha.md"):
            return {
                "path": path,
                "unlinked": [{"path": "Lecture.md", "title": "Lecture", "mentions": [{"line": 1}]}],
            }
        return {"path": path, "unlinked": []}

    monkeypatch.setattr("app.vault.links.review_mentions_with_ai", fake_review)
    progress: list[tuple[int, int, str]] = []
    result = review_wiki_backlinks("TEST", settings, lambda *args: progress.append(args))
    assert result["pages_reviewed"] == 2
    assert result["suggestions"] == 1
    assert [target["title"] for target in result["targets"]] == ["Alpha"]
    assert progress[-1] == (2, 2, "AI link review complete.")


# ---- link_mention ----

def test_link_mention_rewrites_text_to_wikilink(settings):
    target = _write(settings, "Reliability.md", "# Reliability\n")
    source = _write(settings, "Lecture 6.md", "We covered reliability today.\n")
    mention = get_mentions(target, settings)["unlinked"][0]["mentions"][0]
    result = link_mention(
        source, target, mention["line"], mention["start"], mention["end"], settings
    )
    assert result["written"] is True
    assert result["link"] == "[[Reliability|reliability]]"
    content = read_note(source, settings)["content"]
    assert "We covered [[Reliability|reliability]] today." in content


def test_link_mention_exact_case_uses_plain_wikilink(settings):
    target = _write(settings, "Validity.md", "# Validity\n")
    source = _write(settings, "Lecture 7.md", "Validity next week.\n")
    mention = get_mentions(target, settings)["unlinked"][0]["mentions"][0]
    result = link_mention(
        source, target, mention["line"], mention["start"], mention["end"], settings
    )
    assert result["link"] == "[[Validity]]"


def test_link_mention_rejects_stale_offsets(settings):
    target = _write(settings, "Sampling.md", "# Sampling\n")
    source = _write(settings, "Lecture 8.md", "About sampling methods.\n")
    mention = get_mentions(target, settings)["unlinked"][0]["mentions"][0]
    _write(settings, "Lecture 8.md", "Totally rewritten note.\n")
    with pytest.raises(ValueError):
        link_mention(
            source, target, mention["line"], mention["start"], mention["end"], settings
        )


# ---- rename propagation ----

def test_rename_updates_links_preserving_alias_heading_and_embed(settings):
    _write(settings, "Old Name.md", "# Old Name\n")
    other = _write(
        settings,
        "Lecture 10.md",
        "See [[Old Name]], [[Old Name|the notes]], [[Old Name#Part 2]],\n"
        "an embed ![[Old Name]], and [[old name]] in lowercase.\n"
        "[[Old Namesake]] must stay.\n",
    )
    result = rename_note(f"{COURSE}/Old Name.md", f"{COURSE}/New Name.md", settings)
    assert result["links_updated"] == 1
    content = read_note(other, settings)["content"]
    assert "[[New Name]]" in content
    assert "[[New Name|the notes]]" in content
    assert "[[New Name#Part 2]]" in content
    assert "![[New Name]]" in content
    assert content.count("[[New Name") == 5  # lowercase link retargeted too
    assert "[[Old Namesake]]" in content


def test_move_without_rename_touches_no_links(settings):
    _write(settings, "Stable.md", "# Stable\n")
    other = _write(settings, "Lecture 11.md", "See [[Stable]].\n")
    result = rename_note(
        f"{COURSE}/Stable.md", f"{COURSE}/sub/Stable.md", settings
    )
    assert result["links_updated"] == 0
    assert "[[Stable]]" in read_note(other, settings)["content"]


# ---- API ----

def test_backlinks_endpoint_roundtrip(settings):
    from fastapi.testclient import TestClient

    from app.config.settings import get_settings as settings_dep
    from app.main import app

    target = _write(settings, "Reliability.md", "# Reliability\n")
    source = _write(settings, "Lecture 9.md", "Revise reliability plus [[Reliability]].\n")

    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        client = TestClient(app)
        search = client.get("/vault/backlinks/search", params={"q": "Reliability"}).json()
        assert search["count"] >= 1
        assert any(target_hit["path"] == target for target_hit in search["targets"])

        data = client.get("/vault/backlinks", params={"path": target}).json()
        assert [g["path"] for g in data["linked"]] == [source]
        mention = data["unlinked"][0]["mentions"][0]
        res = client.post(
            "/vault/backlinks/link",
            json={
                "source_path": source,
                "target_path": target,
                "line": mention["line"],
                "start": mention["start"],
                "end": mention["end"],
            },
        )
        assert res.status_code == 200
        # Stale offsets after the rewrite are refused, not applied.
        res = client.post(
            "/vault/backlinks/link",
            json={
                "source_path": source,
                "target_path": target,
                "line": mention["line"],
                "start": mention["start"],
                "end": mention["end"],
            },
        )
        assert res.status_code == 409
    finally:
        app.dependency_overrides.pop(settings_dep, None)
