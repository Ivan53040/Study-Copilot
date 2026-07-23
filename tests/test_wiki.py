"""Wiki build pipeline, incremental skip, merging, and graph scoring."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import Chunk, Document, Job, WikiSource
from app.models.chat import ChatResponse
from app.wiki import store
from app.wiki.graph import build_wiki_graph
from app.wiki.service import build_wiki, submit_wiki_build


class ScriptedWikiAdapter:
    """Returns queued responses in order; records how many calls were made."""

    model_name = "scripted"

    def __init__(self, responses: list[str]):
        self._queue = list(responses)
        self.calls = 0

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        self.calls += 1
        return ChatResponse(content=self._queue.pop(0), model=self.model_name)


def _no_progress(current: int, total: int, message: str) -> None:
    pass


def _add_document(
    settings: Settings,
    name: str,
    *,
    title: str,
    content_hash: str,
    chunks: list[str],
    course: str | None = "REIT6811",
    folder: str = "REIT6811 - Research Methods",
) -> int:
    path = Path(settings.vault.root) / folder / name
    with session_scope(settings) as session:
        doc = Document(
            path=str(path), title=title, course=course, content_hash=content_hash
        )
        session.add(doc)
        session.flush()
        for i, text in enumerate(chunks):
            session.add(
                Chunk(document_id=doc.id, chunk_index=i, content=text, course=course)
            )
        return doc.id


def _analysis(summary: str, entities: list[dict], contradictions: list | None = None) -> str:
    return json.dumps(
        {"summary": summary, "entities": entities, "contradictions": contradictions or []}
    )


def _generation(source_body: str, pages: list[dict]) -> str:
    return json.dumps({"source_page_body": source_body, "pages": pages})


def _entity(name: str, *, type_: str = "concept", exists: bool = False) -> dict:
    return {
        "name": name,
        "type": type_,
        "description": f"{name} description",
        "exists_in_wiki": exists,
        "related_pages": [],
    }


def _page(title: str, body: str, *, action: str = "create", type_: str = "concept") -> dict:
    return {
        "title": title,
        "type": type_,
        "action": action,
        "summary": f"{title} summary",
        "body": body,
    }


def test_build_writes_pages_index_log_and_tracks_sources(settings: Settings, db) -> None:
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Reliability is consistency.", "Validity is accuracy."],
    )
    adapter = ScriptedWikiAdapter(
        [
            _analysis(
                "Week 1 measurement lecture.",
                [_entity("Reliability"), _entity("Validity")],
            ),
            _generation(
                "Covers [[Reliability]] and [[Validity]].",
                [
                    _page("Reliability", "Consistency of measurement. See [[Validity]]."),
                    _page("Validity", "Measuring what you intend. See [[Reliability]]."),
                ],
            ),
        ]
    )

    result = build_wiki(
        settings=settings, course="REIT6811", force=False,
        adapter=adapter, progress=_no_progress,
    )

    assert result["processed"] == 1
    assert result["failed"] == 0
    assert sorted(result["pages_created"]) == ["Reliability", "Validity"]

    wiki_dir = Path(settings.vault.root) / "StudyCopilot" / "Wiki" / "REIT6811"
    assert (wiki_dir / "Sources" / "A Lecture.md").is_file()
    assert (wiki_dir / "Concepts" / "Reliability.md").is_file()
    assert (wiki_dir / "Concepts" / "Validity.md").is_file()

    page = store.read_wiki_page(
        "StudyCopilot/Wiki/REIT6811/Concepts/Reliability.md", settings
    )
    assert page["type"] == "concept"
    assert page["course"] == "REIT6811"
    assert page["sources"] == ["REIT6811 - Research Methods/A_lecture.md"]
    assert "[[Validity]]" in page["body"]

    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "[[Reliability]]" in index and "[[Validity]]" in index

    log_lines = [
        line
        for line in (wiki_dir / "log.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("- ")
    ]
    assert len(log_lines) == 1
    assert "source=A Lecture" in log_lines[0] and "status=ok" in log_lines[0]

    with session_scope(settings) as session:
        rows = session.scalars(select(WikiSource)).all()
        assert len(rows) == 1
        assert rows[0].content_hash == "hash-a"
        assert rows[0].status == "ok"


def test_model_wikilink_titles_are_normalized(settings: Settings, db) -> None:
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Research is not the same as learning."],
    )
    adapter = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("[[Research vs Learning]]")]),
            _generation(
                "About [[Research vs Learning]].",
                [_page("[[Research vs Learning]]", "Clean title page.")],
            ),
        ]
    )

    result = build_wiki(
        settings=settings, course="REIT6811", force=False,
        adapter=adapter, progress=_no_progress,
    )

    assert result["pages_created"] == ["Research vs Learning"]
    wiki_dir = Path(settings.vault.root) / "StudyCopilot" / "Wiki" / "REIT6811"
    assert (wiki_dir / "Concepts" / "Research vs Learning.md").is_file()
    assert not (wiki_dir / "Concepts" / "[[Research vs Learning]].md").exists()
    index = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "[[Research vs Learning]]" in index
    assert "[[[[Research vs Learning]]]]" not in index


def test_incremental_skip_and_force_rebuild(settings: Settings, db) -> None:
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Reliability is consistency."],
    )
    first = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("Reliability")]),
            _generation("About [[Reliability]].", [_page("Reliability", "Consistency.")]),
        ]
    )
    build_wiki(settings=settings, course="REIT6811", force=False, adapter=first, progress=_no_progress)

    # Unchanged source: no LLM calls at all.
    empty = ScriptedWikiAdapter([])
    result = build_wiki(
        settings=settings, course="REIT6811", force=False, adapter=empty, progress=_no_progress
    )
    assert result["skipped"] == 1 and result["processed"] == 0
    assert empty.calls == 0

    # force=True reprocesses despite the matching hash.
    forced = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("Reliability", exists=True)]),
            _generation(
                "About [[Reliability]].",
                [_page("Reliability", "MERGED body.", action="update")],
            ),
        ]
    )
    result = build_wiki(
        settings=settings, course="REIT6811", force=True, adapter=forced, progress=_no_progress
    )
    assert result["processed"] == 1


def test_merge_updates_sources_union_and_guards_blind_create(settings: Settings, db) -> None:
    # Ordered scripted responses require sequential processing.
    settings.wiki.max_concurrent_sources = 1
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Reliability is consistency."],
    )
    _add_document(
        settings, "B_tutorial.md", title="B Tutorial", content_hash="hash-b",
        chunks=["Reliability again, plus new angles."],
    )
    adapter = ScriptedWikiAdapter(
        [
            # A_lecture: creates Reliability.
            _analysis("Lecture.", [_entity("Reliability")]),
            _generation("About [[Reliability]].", [_page("Reliability", "Original body.")]),
            # B_tutorial: analysis misses the existing page ("Something Else"),
            # generation then claims to *create* Reliability -> guard must append.
            _analysis("Tutorial.", [_entity("Something Else")]),
            _generation(
                "More on [[Reliability]].",
                [
                    _page("Something Else", "New page."),
                    _page("Reliability", "Blindly regenerated body.", action="create"),
                ],
            ),
        ]
    )
    build_wiki(settings=settings, course="REIT6811", force=False, adapter=adapter, progress=_no_progress)

    page = store.read_wiki_page(
        "StudyCopilot/Wiki/REIT6811/Concepts/Reliability.md", settings
    )
    # Old content preserved, new content appended under a provenance heading.
    assert "Original body." in page["body"]
    assert "## From [[B Tutorial]]" in page["body"]
    assert "Blindly regenerated body." in page["body"]
    assert page["sources"] == [
        "REIT6811 - Research Methods/A_lecture.md",
        "REIT6811 - Research Methods/B_tutorial.md",
    ]


def test_merge_by_rewrite_when_model_saw_existing_body(settings: Settings, db) -> None:
    settings.wiki.max_concurrent_sources = 1
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Reliability is consistency."],
    )
    _add_document(
        settings, "B_tutorial.md", title="B Tutorial", content_hash="hash-b",
        chunks=["Reliability, expanded."],
    )
    adapter = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("Reliability")]),
            _generation("About [[Reliability]].", [_page("Reliability", "Original body.")]),
            # Analysis names the existing page, so its body is sent for merging.
            _analysis("Tutorial.", [_entity("Reliability", exists=True)]),
            _generation(
                "More on [[Reliability]].",
                [_page("Reliability", "Merged: original plus new.", action="update")],
            ),
        ]
    )
    build_wiki(settings=settings, course="REIT6811", force=False, adapter=adapter, progress=_no_progress)

    page = store.read_wiki_page(
        "StudyCopilot/Wiki/REIT6811/Concepts/Reliability.md", settings
    )
    assert page["body"].startswith("Merged: original plus new.")
    assert "Original body." not in page["body"]
    assert len(page["sources"]) == 2


def test_bad_json_fails_one_source_but_continues(settings: Settings, db) -> None:
    settings.wiki.max_concurrent_sources = 1
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Garbage source."],
    )
    _add_document(
        settings, "B_tutorial.md", title="B Tutorial", content_hash="hash-b",
        chunks=["Good source."],
    )
    adapter = ScriptedWikiAdapter(
        [
            "definitely not json",  # A analysis, attempt 1
            "still not json",       # A analysis, retry -> source fails
            _analysis("Tutorial.", [_entity("Validity")]),
            _generation("About [[Validity]].", [_page("Validity", "Accuracy.")]),
        ]
    )
    result = build_wiki(
        settings=settings, course="REIT6811", force=False, adapter=adapter, progress=_no_progress
    )
    assert result["failed"] == 1 and result["processed"] == 1

    with session_scope(settings) as session:
        rows = {row.status for row in session.scalars(select(WikiSource)).all()}
        assert rows == {"failed", "ok"}

    page = store.read_wiki_page(
        "StudyCopilot/Wiki/REIT6811/Concepts/Validity.md", settings
    )
    assert page is not None

    # The failed source is retried on the next run; the succeeded one is skipped.
    retry = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("Reliability")]),
            _generation("About [[Reliability]].", [_page("Reliability", "Consistency.")]),
        ]
    )
    result = build_wiki(
        settings=settings, course="REIT6811", force=False, adapter=retry, progress=_no_progress
    )
    assert result["processed"] == 1 and result["skipped"] == 1


class ParallelScriptedAdapter:
    """Thread-safe adapter that picks responses by source title in the prompt."""

    model_name = "parallel-scripted"

    def __init__(self, per_source: dict[str, list[str]]):
        self._per_source = {key: list(vals) for key, vals in per_source.items()}
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(0.1)  # give workers a chance to overlap
        user = next(m.content for m in messages if m.role == "user")
        key = next(k for k in self._per_source if f"({k}," in user)
        with self._lock:
            content = self._per_source[key].pop(0)
            self._active -= 1
        return ChatResponse(content=content, model=self.model_name)


def test_parallel_build_processes_all_sources_concurrently(settings: Settings, db) -> None:
    assert settings.wiki.max_concurrent_sources >= 4  # config default
    titles = ["Doc A", "Doc B", "Doc C"]
    for i, title in enumerate(titles):
        _add_document(
            settings, f"{title.replace(' ', '_')}.md", title=title,
            content_hash=f"hash-{i}", chunks=[f"Content of {title}."],
        )
    adapter = ParallelScriptedAdapter(
        {
            title: [
                _analysis(f"{title} summary.", [_entity(f"Topic {title[-1]}")]),
                _generation(
                    f"About [[Topic {title[-1]}]].",
                    [_page(f"Topic {title[-1]}", f"Body for {title}.")],
                ),
            ]
            for title in titles
        }
    )

    result = build_wiki(
        settings=settings, course="REIT6811", force=False,
        adapter=adapter, progress=_no_progress,
    )

    assert result["processed"] == 3 and result["failed"] == 0
    assert sorted(result["pages_created"]) == ["Topic A", "Topic B", "Topic C"]
    # The LLM calls genuinely overlapped across worker threads.
    assert adapter.max_active >= 2
    for letter in "ABC":
        page = store.read_wiki_page(
            f"StudyCopilot/Wiki/REIT6811/Concepts/Topic {letter}.md", settings
        )
        assert page is not None

    with session_scope(settings) as session:
        rows = session.scalars(select(WikiSource)).all()
        assert len(rows) == 3 and all(row.status == "ok" for row in rows)


def test_folder_scoped_build_uses_folder_notes_regardless_of_course(
    settings: Settings, db
) -> None:
    # Unclassified side-project notes live under a folder, not a course.
    _add_document(
        settings, "plan.md", title="Project Plan", content_hash="hash-p",
        chunks=["The gateway proxies MCP traffic."],
        course=None, folder="Side Project",
    )
    # A study note in a different folder must NOT be pulled into this wiki.
    _add_document(
        settings, "week1.md", title="Week 1", content_hash="hash-w",
        chunks=["Reliability is consistency."], course="REIT6811",
    )
    scope_path = str(Path(settings.vault.root) / "Side Project")
    adapter = ScriptedWikiAdapter(
        [
            _analysis("Plan.", [_entity("MCP Gateway")]),
            _generation("About [[MCP Gateway]].", [_page("MCP Gateway", "A proxy.")]),
        ]
    )

    result = build_wiki(
        settings=settings, course=None, force=False,
        adapter=adapter, progress=_no_progress,
        scope_path=scope_path, name="Side Project",
    )

    assert result["course"] == "Side Project"
    assert result["processed"] == 1  # only the folder note, not the study note
    page = store.read_wiki_page(
        "StudyCopilot/Wiki/Side Project/Concepts/MCP Gateway.md", settings
    )
    assert page is not None
    assert page["course"] == "Side Project"
    # The wiki is readable under its folder-name label.
    assert store.list_wiki_pages("Side Project", settings)
    assert not store.list_wiki_pages("REIT6811", settings)


def test_graph_four_signals_and_communities(settings: Settings) -> None:
    def write(title: str, type_: str, sources: list[str], body: str) -> None:
        rel = store.page_rel_path("REIT6811", type_, title, settings)
        meta = {
            "title": title, "type": type_, "course": "REIT6811",
            "sources": sources, "summary": f"{title} summary",
            "source_type": "ai-generated", "reviewed_by_user": False,
            "updated_at": "2026-07-07",
        }
        store.write_page(rel, meta, body, settings)

    # Alpha <-> Beta: direct link + identical sources + same type = 3 + 4 + 1.
    write("Alpha", "concept", ["s1.md"], "Links to [[Beta]].")
    write("Beta", "concept", ["s1.md"], "No outgoing links.")
    # Hub triangle: A2/B2 share a source and both link Hub (Adamic-Adar).
    write("A2", "concept", ["s3.md"], "See [[Hub]].")
    write("B2", "concept", ["s3.md"], "See [[Hub]].")
    write("Hub", "entity", ["s4.md"], "Hub page.")
    # Isolated page: single-node community, flagged.
    write("Gamma", "entity", ["s2.md"], "Alone.")

    graph = build_wiki_graph(settings, "REIT6811")
    edges = {
        tuple(sorted((e["source"].rsplit("/", 1)[-1], e["target"].rsplit("/", 1)[-1]))): e
        for e in graph["edges"]
    }

    alpha_beta = edges[("Alpha.md", "Beta.md")]
    assert alpha_beta["weight"] == pytest.approx(8.0)
    assert alpha_beta["signals"] == {
        "link": 3.0, "source": 4.0, "adamic": 0.0, "title": 0.0, "type": 1.0
    }

    # A2-B2: no direct link; shared source (Jaccard 1) -> 4.0; Adamic-Adar via
    # Hub (degree 2): 1.5 * min(1, (1/ln 2)/2) ~ 1.082; same type -> 1.0.
    a2_b2 = edges[("A2.md", "B2.md")]
    assert a2_b2["signals"]["link"] == 0.0
    assert a2_b2["signals"]["source"] == pytest.approx(4.0)
    assert a2_b2["signals"]["adamic"] == pytest.approx(1.5 * (1 / 0.6931) / 2, abs=1e-3)
    assert a2_b2["weight"] == pytest.approx(4.0 + 1.0 + 1.5 * (1 / 0.6931) / 2, abs=1e-3)

    nodes = {n["title"]: n for n in graph["nodes"]}
    # Linked pairs share a community; the isolated node is flagged.
    assert nodes["Alpha"]["community"] == nodes["Beta"]["community"]
    assert nodes["A2"]["community"] == nodes["B2"]["community"]
    assert nodes["Gamma"]["flagged"] is True
    assert nodes["Alpha"]["flagged"] is False
    assert graph["stats"]["pages"] == 6


def test_graph_bridges_equivalent_concepts_across_courses(settings: Settings) -> None:
    def write(course: str, title: str) -> str:
        rel = store.page_rel_path(course, "concept", title, settings)
        store.write_page(
            rel,
            {
                "title": title,
                "type": "concept",
                "course": course,
                "sources": [],
                "summary": "",
            },
            f"# {title}",
            settings,
        )
        return rel

    first = write("COMP4703", "Object-Oriented Programming")
    second = write("CSSE7030", "Object Oriented Programming")
    graph = build_wiki_graph(settings, None)
    edge = next(
        edge
        for edge in graph["edges"]
        if {edge["source"], edge["target"]} == {first, second}
    )
    assert edge["signals"]["title"] == 3.0
    assert graph["stats"]["cross_course_edges"] == 1


def test_all_courses_lists_existing_course_wikis(settings: Settings) -> None:
    store.write_page(
        store.page_rel_path("REIT6811", "concept", "Reliability", settings),
        {
            "title": "Reliability",
            "type": "concept",
            "course": "REIT6811",
            "sources": ["s1.md"],
            "summary": "Consistency.",
            "source_type": "ai-generated",
            "reviewed_by_user": False,
            "updated_at": "2026-07-07",
        },
        "Consistency of measurement.",
        settings,
    )

    pages = store.list_wiki_pages(None, settings)

    assert [page["title"] for page in pages] == ["Reliability"]


def test_wiki_alias_lookup_and_course_map_index(settings: Settings) -> None:
    canonical_rel = store.page_rel_path("REIT6811", "concept", "Function", settings)
    store.write_page(
        canonical_rel,
        {
            "title": "Function",
            "type": "concept",
            "course": "REIT6811",
            "aliases": ["Functions"],
            "sources": ["notes.md"],
            "summary": "A reusable mapping.",
        },
        "A function maps inputs to outputs.",
        settings,
    )
    map_rel = store.page_rel_path("REIT6811", "map", "Week 1", settings)
    store.write_page(
        map_rel,
        {
            "title": "Week 1",
            "type": "map",
            "course": "REIT6811",
            "sources": ["week1.md"],
            "summary": "Week 1 navigation.",
        },
        "Links to [[Function]].",
        settings,
    )

    found = store.find_existing_page("REIT6811", "Functions", settings)
    assert found is not None
    assert found["path"] == canonical_rel
    store.write_page(
        store.page_rel_path("REIT6811", "source", "Functions", settings),
        {
            "title": "Functions",
            "type": "source",
            "course": "REIT6811",
            "sources": ["lecture.md"],
            "summary": "A same-named source summary.",
        },
        "Lecture summary.",
        settings,
    )
    assert store.find_existing_page("REIT6811", "Functions", settings)["path"] == canonical_rel
    index = store.render_index("REIT6811", store.list_wiki_pages("REIT6811", settings))
    assert "## Course Maps" in index
    assert "[[Week 1]]" in index


def test_all_course_build_writes_aggregate_index(settings: Settings, db) -> None:
    # Ordered scripted responses require sequential processing.
    settings.wiki.max_concurrent_sources = 1
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Reliability is consistency."], course="REIT6811",
    )
    _add_document(
        settings, "B_lecture.md", title="B Lecture", content_hash="hash-b",
        chunks=["Validity is accuracy."], course="CSSE7030",
    )
    adapter = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("Validity")]),
            _generation("About [[Validity]].", [_page("Validity", "Accuracy.")]),
            _analysis("Lecture.", [_entity("Reliability")]),
            _generation("About [[Reliability]].", [_page("Reliability", "Consistency.")]),
        ]
    )

    result = build_wiki(
        settings=settings, course=None, force=False,
        adapter=adapter, progress=_no_progress,
    )

    assert "StudyCopilot/Wiki/All Courses/index.md" in result["index_paths"]
    index = (
        Path(settings.vault.root)
        / "StudyCopilot"
        / "Wiki"
        / "All Courses"
        / "index.md"
    ).read_text(encoding="utf-8")
    assert "[[Reliability]]" in index
    assert "[[Validity]]" in index


def test_wiki_build_indexes_pages_for_search(settings: Settings, db) -> None:
    settings.vault.read_paths.append("StudyCopilot/**")
    _add_document(
        settings, "A_lecture.md", title="A Lecture", content_hash="hash-a",
        chunks=["Reliability is consistency."],
    )
    adapter = ScriptedWikiAdapter(
        [
            _analysis("Lecture.", [_entity("Reliability")]),
            _generation("About [[Reliability]].", [_page("Reliability", "Consistency.")]),
        ]
    )

    result = build_wiki(
        settings=settings, course="REIT6811", force=False,
        adapter=adapter, progress=_no_progress,
    )

    assert result["indexed_pages"] == 2
    with session_scope(settings) as session:
        wiki_docs = session.scalars(
            select(Document).where(Document.path.contains("StudyCopilot"))
        ).all()
        assert sorted(doc.title for doc in wiki_docs) == [
            "A Lecture",
            "Reliability",
        ]
        assert {doc.course for doc in wiki_docs} == {"REIT6811"}
        assert {doc.source_type for doc in wiki_docs} >= {"ai-generated"}
        assert sum(len(doc.chunks) for doc in wiki_docs) > 0


def test_submit_wiki_build_creates_job(settings: Settings, db, monkeypatch) -> None:
    # Keep the real worker thread out of the test database.
    monkeypatch.setattr("app.jobs.service.ensure_worker", lambda: None)
    created = submit_wiki_build(settings=settings, course="REIT6811", force=True)
    assert created["type"] == "wiki_build"
    assert created["payload"] == {
        "course": "REIT6811",
        "scope_path": None,
        "name": None,
        "force": True,
    }
    with session_scope(settings) as session:
        job = session.get(Job, created["id"])
        assert job is not None and job.type == "wiki_build"
