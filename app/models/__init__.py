"""Model adapters: embeddings and chat."""

from app.models.chat import (
    ChatAdapter,
    ChatError,
    ChatMessage,
    ChatResponse,
    EchoChatAdapter,
    LMStudioChatAdapter,
    get_chat_adapter,
)
from app.models.embeddings import (
    EmbeddingProvider,
    HashingEmbeddings,
    OpenAICompatibleEmbeddings,
    get_embedding_provider,
)

__all__ = [
    "ChatAdapter",
    "ChatError",
    "ChatMessage",
    "ChatResponse",
    "EchoChatAdapter",
    "LMStudioChatAdapter",
    "get_chat_adapter",
    "EmbeddingProvider",
    "HashingEmbeddings",
    "OpenAICompatibleEmbeddings",
    "get_embedding_provider",
]
