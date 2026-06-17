"""Past-paper analysis + mock-exam generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator

from app.config.settings import Settings, get_settings
from app.exams.past_papers import analyze_past_papers, list_past_paper_questions
from app.generation.quizzes import generate_quiz

router = APIRouter(tags=["exams"])


class AnalyzeRequest(BaseModel):
    course: str | None = None


class MockExamRequest(BaseModel):
    course: str | None = None
    week: int | None = None
    topic: str | None = None
    num_questions: int = 5

    @model_validator(mode="after")
    def _scope(self):
        if not (self.course or self.topic):
            raise ValueError("Provide at least a course or a topic.")
        return self


@router.post("/past-papers/analyze")
def post_analyze(
    req: AnalyzeRequest, settings: Settings = Depends(get_settings)
) -> dict:
    return analyze_past_papers(course=req.course, settings=settings).as_dict()


@router.get("/past-papers/{course}")
def get_past_papers(
    course: str, settings: Settings = Depends(get_settings)
) -> dict:
    questions = list_past_paper_questions(course=course, settings=settings)
    return {"course": course, "count": len(questions), "questions": questions}


@router.post("/exams/generate")
def post_mock_exam(
    req: MockExamRequest, settings: Settings = Depends(get_settings)
) -> dict:
    result = generate_quiz(
        course=req.course,
        week=req.week,
        topic=req.topic,
        num_questions=req.num_questions,
        style="exam",
        settings=settings,
    )
    return result.as_dict()
