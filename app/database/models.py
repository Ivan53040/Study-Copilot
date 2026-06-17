"""SQLAlchemy ORM models.

Phase 1 covers ``Document`` and ``Chunk``. Learning-history tables
(Concept, LearningEvent, ConceptProgress) arrive in Phase 5.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
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


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    title: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # Citations/sources/warnings attached to an assistant turn.
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (
        UniqueConstraint("course", "name", name="uq_concept_course_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    importance: Mapped[int] = mapped_column(Integer, default=3)  # 1..5
    exam_frequency: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    progress: Mapped["ConceptProgress | None"] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class ConceptProgress(Base):
    __tablename__ = "concept_progress"

    concept_id: Mapped[int] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="weak")
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    incorrect_count: Mapped[int] = mapped_column(Integer, default=0)
    partial_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    next_review: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    concept: Mapped["Concept"] = relationship(back_populates="progress")


class LearningEvent(Base):
    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True, default=None
    )
    # correct | incorrect | partial | note_read | concept_review
    event_type: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=1.0)
    difficulty: Mapped[str | None] = mapped_column(String, default=None)
    source_reference: Mapped[str | None] = mapped_column(String, default=None)
    quiz_question_id: Mapped[int | None] = mapped_column(Integer, default=None)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    week: Mapped[int | None] = mapped_column(Integer, default=None)
    topic: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    score: Mapped[float | None] = mapped_column(Float, default=None)
    total: Mapped[float | None] = mapped_column(Float, default=None)

    questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuizQuestion.index",
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)  # mcq | short
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSON, default=None)
    answer_key: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text, default=None)
    difficulty: Mapped[str] = mapped_column(String, default="medium")
    concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), default=None
    )
    concept_name: Mapped[str | None] = mapped_column(String, default=None)
    sources: Mapped[list] = mapped_column(JSON, default=list)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")


class PastPaperQuestion(Base):
    __tablename__ = "past_paper_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    course: Mapped[str | None] = mapped_column(String, index=True, default=None)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    number: Mapped[str | None] = mapped_column(String, default=None)
    text: Mapped[str] = mapped_column(Text)
    marks: Mapped[int | None] = mapped_column(Integer, default=None)
    concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True, default=None
    )
    concept_name: Mapped[str | None] = mapped_column(String, default=None)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


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
