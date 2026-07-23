"""Shared SQL metadata-filter builder for keyword + vector search."""

from __future__ import annotations

from app.retrieval.types import MetadataFilter


def metadata_clause(flt: MetadataFilter, params: dict, alias: str = "c") -> str:
    """Build an ``AND ...`` SQL fragment from a MetadataFilter and bind params."""
    clauses = []
    if flt.course:
        clauses.append(f"upper({alias}.course) = :course")
        params["course"] = flt.course.replace(" ", "").upper()
    if flt.path_prefix:
        clauses.append("lower(replace(d.path, '\\', '/')) LIKE :path_prefix")
        params["path_prefix"] = flt.path_prefix.replace("\\", "/").lower().rstrip("/") + "/%"
    if flt.document_ids:
        keys = []
        for index, document_id in enumerate(flt.document_ids):
            key = f"document_id_{index}"
            keys.append(f":{key}")
            params[key] = document_id
        clauses.append(f"c.document_id IN ({', '.join(keys)})")
    if flt.week is not None:
        clauses.append(f"{alias}.week = :week")
        params["week"] = flt.week
    if flt.source_type:
        clauses.append(f"{alias}.source_type = :source_type")
        params["source_type"] = flt.source_type
    if flt.max_trust_level is not None:
        clauses.append(f"{alias}.trust_level <= :max_trust")
        params["max_trust"] = flt.max_trust_level
    return (" AND " + " AND ".join(clauses)) if clauses else ""
