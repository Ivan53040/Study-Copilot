"""Quiz generation/submission + concept progress endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.generation.marking import submit_quiz
from app.generation.quizzes import generate_quiz
from app.learning.service import get_progress

router = APIRouter(tags=["quizzes"])


class QuizRequest(BaseModel):
    course: str | None = None
    week: int | None = None
    topic: str | None = None
    num_questions: int = 5

    @model_validator(mode="after")
    def _scope(self):
        if not (self.course or self.topic):
            raise ValueError("Provide at least a course or a topic.")
        return self


class AnswerItem(BaseModel):
    question_id: int
    answer: str


class SubmitRequest(BaseModel):
    answers: list[AnswerItem]


@router.post("/quizzes/generate")
def post_generate(
    req: QuizRequest, settings: Settings = Depends(get_settings)
) -> dict:
    result = generate_quiz(
        course=req.course,
        week=req.week,
        topic=req.topic,
        num_questions=req.num_questions,
        settings=settings,
    )
    return result.as_dict()


@router.post("/quizzes/{quiz_id}/submit")
def post_submit(
    quiz_id: int, req: SubmitRequest, settings: Settings = Depends(get_settings)
) -> dict:
    answers = {a.question_id: a.answer for a in req.answers}
    try:
        return submit_quiz(quiz_id, answers, settings=settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/progress/{course}")
def get_course_progress(
    course: str, settings: Settings = Depends(get_settings)
) -> dict:
    with session_scope(settings) as session:
        rows = get_progress(session, course=course)
    return {"course": course.replace(" ", "").upper(), "concepts": rows}
