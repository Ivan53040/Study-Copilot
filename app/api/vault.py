"""Note-workspace endpoints: browse, read, edit, graph (whole vault)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.security.paths import PathSecurityError
from app.vault.service import (
    build_graph,
    create_folder,
    copy_note,
    delete_note,
    export_pdf,
    import_files,
    list_tree,
    list_versions,
    merge_notes,
    move_item,
    open_external,
    read_note,
    rename_note,
    restore_version,
    reveal_note,
    search_notes,
    set_note_property,
    write_note,
)
from app.vault.links import (
    get_mentions,
    link_mention,
    review_mentions_with_ai,
    search_backlink_candidates,
)
from app.vault.organizer import apply_organization, preview_organization
from app.vault.formatter import preview_document_format

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


class MoveReq(BaseModel):
    from_path: str
    to_folder: str = ""


class ImportReq(BaseModel):
    source_paths: list[str]
    target_folder: str = ""


class MergeReq(BaseModel):
    target_path: str
    source_path: str
    delete_source: bool = False


class PropertyReq(BaseModel):
    path: str
    key: str
    value: str


class RestoreReq(BaseModel):
    path: str
    version_id: str


class OrganizeMove(BaseModel):
    from_path: str
    to_path: str
    reason: str = ""


class OrganizeApply(BaseModel):
    moves: list[OrganizeMove]


class FormatPreviewReq(BaseModel):
    path: str
    content: str | None = None


class LinkMentionReq(BaseModel):
    source_path: str
    target_path: str
    line: int
    start: int
    end: int
    aliases: list[str] = []


class BacklinkReviewReq(BaseModel):
    path: str
    aliases: list[str] = []


@router.get("/tree")
def get_tree(settings: Settings = Depends(get_settings)) -> dict:
    return list_tree(settings)


@router.post("/organize/preview")
def post_organize_preview(settings: Settings = Depends(get_settings)) -> dict:
    try:
        return preview_organization(settings)
    except (RuntimeError, PathSecurityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/organize/apply")
def post_organize_apply(
    req: OrganizeApply, settings: Settings = Depends(get_settings)
) -> dict:
    moves = [
        {"from": move.from_path, "to": move.to_path, "reason": move.reason}
        for move in req.moves
    ]
    try:
        return apply_organization(moves, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/format/preview")
def post_format_preview(
    req: FormatPreviewReq, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return preview_document_format(req.path, req.content, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/copy")
def post_copy(req: RenameReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return copy_note(req.from_path, req.to_path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/move")
def post_move(req: MoveReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return move_item(req.from_path, req.to_folder, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/import")
def post_import(req: ImportReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return import_files(req.source_paths, req.target_folder, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/merge")
def post_merge(req: MergeReq, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return merge_notes(
            req.target_path,
            req.source_path,
            req.delete_source,
            settings,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/property")
def post_property(
    req: PropertyReq, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return set_note_property(req.path, req.key, req.value, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/versions")
def get_versions(
    path: str = Query(...), settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return {"path": path, "versions": list_versions(path, settings)}
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/versions/restore")
def post_restore(
    req: RestoreReq, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return restore_version(req.path, req.version_id, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.get("/backlinks")
def get_backlinks(
    path: str = Query(...),
    alias: list[str] = Query(default=[]),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return get_mentions(path, settings, aliases=alias)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backlinks/search")
def get_backlink_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(8, ge=1, le=20),
    mention_limit: int = Query(80, ge=1, le=300),
    settings: Settings = Depends(get_settings),
) -> dict:
    return search_backlink_candidates(
        q, settings, target_limit=limit, mention_limit=mention_limit
    )


@router.post("/backlinks/review")
def post_backlink_review(
    req: BacklinkReviewReq, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return review_mentions_with_ai(req.path, settings, aliases=req.aliases)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/backlinks/link")
def post_backlink_link(
    req: LinkMentionReq, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return link_mention(
            req.source_path,
            req.target_path,
            req.line,
            req.start,
            req.end,
            settings,
            aliases=req.aliases,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/graph")
def get_graph(settings: Settings = Depends(get_settings)) -> dict:
    return build_graph(settings)


@router.get("/search")
def get_search(
    q: str = "", settings: Settings = Depends(get_settings)
) -> dict:
    return {"results": search_notes(q, settings)}
