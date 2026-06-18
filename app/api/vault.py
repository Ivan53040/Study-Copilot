"""Note-workspace endpoints: browse, read, edit, graph (whole vault)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.security.paths import PathSecurityError
from app.vault.service import (
    build_graph,
    list_tree,
    read_note,
    search_notes,
    write_note,
)

router = APIRouter(prefix="/vault", tags=["vault"])


class NoteWrite(BaseModel):
    path: str
    content: str


@router.get("/tree")
def get_tree(settings: Settings = Depends(get_settings)) -> dict:
    return list_tree(settings)


@router.get("/note")
def get_note(
    path: str = Query(...), settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return read_note(path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/note")
def put_note(req: NoteWrite, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return write_note(req.path, req.content, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/graph")
def get_graph(settings: Settings = Depends(get_settings)) -> dict:
    return build_graph(settings)


@router.get("/search")
def get_search(
    q: str = "", settings: Settings = Depends(get_settings)
) -> dict:
    return {"results": search_notes(q, settings)}
