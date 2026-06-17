"""Model adapters: embeddings now; chat/LLM in Phase 3."""

from app.models.embeddings import (
    EmbeddingProvider,
    HashingEmbeddings,
    OpenAICompatibleEmbeddings,
    get_embedding_provider,
)

__all__ = [
    "EmbeddingProvider",
    "HashingEmbeddings",
    "OpenAICompatibleEmbeddings",
    "get_embedding_provider",
]
