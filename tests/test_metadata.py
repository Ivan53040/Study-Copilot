"""Classification tests."""

from __future__ import annotations

from app.ingestion.metadata import TRUST_LEVELS, classify


def test_frontmatter_wins():
    cls = classify(
        "REIT6811_Week4_Revision_Notes.md",
        frontmatter={
            "title": "Custom Title",
            "course": "REIT6811",
            "week": 4,
            "source_type": "official-course-material",
        },
    )
    assert cls.title == "Custom Title"
    assert cls.course == "REIT6811"
    assert cls.week == 4
    assert cls.source_type == "official-course-material"
    assert cls.trust_level == TRUST_LEVELS["official-course-material"]


def test_infer_course_and_week_from_filename():
    cls = classify("REIT6811_Week10_Revision_Notes.md")
    assert cls.course == "REIT6811"
    assert cls.week == 10
    assert cls.document_type == "revision-note"
    assert cls.source_type == "user-note"


def test_pdf_defaults_to_past_paper_trust():
    cls = classify(
        "Semester_1_Examinations_2025_REIT6811.pdf",
        course_hint="REIT6811",
        source_type_hint="past-paper",
    )
    assert cls.course == "REIT6811"
    assert cls.source_type == "past-paper"
    assert cls.trust_level == TRUST_LEVELS["past-paper"]


def test_lecture_materials_are_trusted_lecture_sources(tmp_path):
    cls = classify(tmp_path / "Lecture Materials" / "DECO7250 Week 1.pptx")
    assert cls.course == "DECO7250"
    assert cls.document_type == "presentation"
    assert cls.source_type == "lecture-source"
    assert cls.trust_level == TRUST_LEVELS["lecture-source"]


def test_marking_guide_detected():
    cls = classify("REIT6811_Mock_Exam_1_Marking_Guide.md")
    assert cls.document_type == "marking-guide"


def test_explicit_trust_level_override():
    cls = classify("notes.md", frontmatter={"trust_level": 1})
    assert cls.trust_level == 1


def test_course_label_variants_unify_to_code():
    # Frontmatter full name, regex-inferred code, and lowercase all collapse.
    a = classify("x.md", frontmatter={"course": "REIT6811 - Research Methods"})
    b = classify("REIT6811_Week1_Revision_Notes.md")
    c = classify("y.md", frontmatter={"course": "reit6811"})
    assert a.course == b.course == c.course == "REIT6811"
