"""Note-workspace endpoints: browse, read, edit, graph (whole vault)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.security.paths import PathSecurityError
from app.vault.service import (
    build_graph,
    create_folder,
    delete_note,
    export_pdf,
    list_tree,
    open_external,
    read_note,
    rename_note,
    reveal_note,
    search_notes,
    write_note,
)

router = APIRouter(prefix="/vault", tags=["vault"])


class NoteWrite(BaseModel):
    path: str
    content: str


class FolderCreate(BaseModel):
    path: str


class RenameReq(BaseModel):
    from_path: str
    to_path: str


class PathReq(BaseModel):
    path: str


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


@router.post("/folder")
def post_folder(
    req: FolderCreate, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return create_folder(req.path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/rename")
def post_rename(req: RenameReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return rename_note(req.from_path, req.to_path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/delete")
def post_delete(req: PathReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return delete_note(req.path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reveal")
def post_reveal(req: PathReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return reveal_note(req.path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/open-external")
def post_open(req: PathReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return open_external(req.path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/export-pdf")
def post_export_pdf(req: PathReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return export_pdf(req.path, settings)
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
