"""Wiki endpoints: build job, page catalog, knowledge graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.wiki import store
from app.wiki.graph import build_wiki_graph
from app.wiki.service import submit_wiki_build, submit_wiki_link_review

router = APIRouter(prefix="/wiki", tags=["wiki"])


class WikiBuildRequest(BaseModel):
    # Build by course (existing) OR by an arbitrary vault folder (scope_path).
    course: str | None = None
    scope_path: str | None = None
    # Wiki namespace for a folder build; defaults to the folder name.
    name: str | None = None
    force: bool = False


class WikiLinkReviewRequest(BaseModel):
    course: str | None = None


@router.post("/build")
def build(req: WikiBuildRequest, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return submit_wiki_build(
            settings=settings,
            course=req.course,
            scope_path=req.scope_path,
            name=req.name,
            force=req.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backlinks/review")
def review_backlinks(
    req: WikiLinkReviewRequest, settings: Settings = Depends(get_settings)
) -> dict:
    return submit_wiki_link_review(settings=settings, course=req.course)


@router.get("/pages")
def pages(course: str | None = None, settings: Settings = Depends(get_settings)) -> dict:
    items = [
        {key: page[key] for key in ("path", "title", "type", "sources", "summary", "updated_at")}
        for page in store.list_wiki_pages(course, settings)
    ]
    course_dir = store.wiki_course_dir(course, settings)
    return {
        "course": course,
        "pages": items,
        "has_purpose": store.has_purpose(course, settings),
        "index_path": f"{course_dir}/index.md" if items else None,
        "log_path": f"{course_dir}/log.md",
        "purpose_path": f"{course_dir}/purpose.md",
    }


@router.get("/graph")
def graph(course: str | None = None, settings: Settings = Depends(get_settings)) -> dict:
    return build_wiki_graph(settings, course)
