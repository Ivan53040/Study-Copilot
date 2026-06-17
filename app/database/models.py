"""SQLAlchemy ORM models.

Phase 1 covers ``Document`` and ``Chunk``. Learning-history tables
(Concept, LearningEvent, ConceptProgress) arrive in Phase 5.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Absolute path on disk, the natural unique key for a source file.
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    title: Mapped[str] = mapped_column(String)

    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    week: Mapped[int | None] = mapped_column(Integer, default=None)
    document_type: Mapped[str | None] = mapped_column(String, default=None)
    source_type: Mapped[str | None] = mapped_column(String, default=None)
    # 1 = most trusted (official material) ... 8 = least (external web).
    trust_level: Mapped[int] = mapped_column(Integer, default=5)

    # sha256 of file bytes; lets us skip unchanged files on re-scan.
    content_hash: Mapped[str] = mapped_column(String, index=True)
    file_modified_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    modified_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_index"),
        Index("ix_chunk_document", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)

    heading: Mapped[str | None] = mapped_column(String, default=None)
    page_number: Mapped[int | None] = mapped_column(Integer, default=None)

    # Denormalised source context copied from the parent document so that a
    # retrieved chunk carries everything needed to cite it.
    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    week: Mapped[int | None] = mapped_column(Integer, default=None)
    source_type: Mapped[str | None] = mapped_column(String, default=None)
    trust_level: Mapped[int] = mapped_column(Integer, default=5)

    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped["Document"] = relationship(back_populates="chunks")
    embedding: Mapped["ChunkEmbedding | None"] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String, index=True)
    dim: Mapped[int] = mapped_column(Integer)
    # float32 vector stored as raw bytes (np.frombuffer to read back).
    vector: Mapped[bytes] = mapped_column(LargeBinary)

    chunk: Mapped["Chunk"] = relationship(back_populates="embedding")
