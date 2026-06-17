"""Search endpoint: hybrid retrieval with citations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.retrieval.citations import format_citation
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str
    course: str | None = None
    week: int | None = None
    source_type: str | None = None
    max_trust_level: int | None = None
    limit: int | None = None
    include_content: bool = True


@router.post("/search")
def post_search(
    req: SearchRequest, settings: Settings = Depends(get_settings)
) -> dict:
    flt = MetadataFilter(
        course=req.course,
        week=req.week,
        source_type=req.source_type,
        max_trust_level=req.max_trust_level,
    )
    resp = search(req.query, settings=settings, flt=flt, final_limit=req.limit)
    return {
        "query": resp.query,
        "used_vector": resp.used_vector,
        "note": resp.note,
        "count": len(resp.hits),
        "results": [
            {
                **hit.as_dict(include_content=req.include_content),
                "citation": format_citation(hit),
            }
            for hit in resp.hits
        ],
    }
