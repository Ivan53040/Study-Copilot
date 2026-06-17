"""Compute and store chunk embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, ChunkEmbedding
from app.logging_config import get_logger
from app.models.embeddings import EmbeddingProvider, get_embedding_provider

logger = get_logger("retrieval.indexing")


@dataclass
class IndexReport:
    model: str
    embedded: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "embedded": self.embedded,
            "skipped": self.skipped,
            "errors": self.errors or [],
        }


def _to_blob(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _chunks_needing_embedding(session: Session, model: str) -> list[Chunk]:
    """Chunks with no embedding, or whose embedding came from another model."""
    have = {
        cid: m
        for cid, m in session.execute(
            select(ChunkEmbedding.chunk_id, ChunkEmbedding.model)
        ).all()
    }
    return [
        c
        for c in session.scalars(select(Chunk)).all()
        if have.get(c.id) != model
    ]


def index_embeddings(
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
    *,
    reindex: bool = False,
) -> IndexReport:
    settings = settings or get_settings()
    provider = provider or get_embedding_provider(settings)
    model = provider.model_name
    batch_size = settings.embeddings.batch_size
    report = IndexReport(model=model, errors=[])

    with session_scope(settings) as session:
        if reindex:
            session.query(ChunkEmbedding).delete()
            session.flush()

        targets = _chunks_needing_embedding(session, model)
        total = session.query(Chunk).count()
        report.skipped = total - len(targets)

        for start in range(0, len(targets), batch_size):
            batch = targets[start : start + batch_size]
            try:
                vectors = provider.embed([c.content for c in batch])
            except Exception as exc:  # network/model errors -> stop, report
                logger.exception("Embedding batch failed")
                report.errors.append(str(exc))
                break
            for chunk, vec in zip(batch, vectors):
                session.merge(
                    ChunkEmbedding(
                        chunk_id=chunk.id,
                        model=model,
                        dim=len(vec),
                        vector=_to_blob(vec),
                    )
                )
                report.embedded += 1
            session.flush()

    logger.info("Embedding index: %s", report.as_dict())
    return report
