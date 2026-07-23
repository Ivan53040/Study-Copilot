"""Model adapters: embeddings and chat."""

from app.models.chat import (
    AnthropicChatAdapter,
    ChatAdapter,
    ChatError,
    ChatMessage,
    ChatResponse,
    EchoChatAdapter,
    LMStudioChatAdapter,
    OpenAIChatAdapter,
    get_chat_adapter,
)
from app.models.embeddings import (
    EmbeddingProvider,
    HashingEmbeddings,
    OpenAICompatibleEmbeddings,
    get_embedding_provider,
)

__all__ = [
    "AnthropicChatAdapter",
    "ChatAdapter",
    "ChatError",
    "ChatMessage",
    "ChatResponse",
    "EchoChatAdapter",
    "LMStudioChatAdapter",
    "OpenAIChatAdapter",
    "get_chat_adapter",
    "EmbeddingProvider",
    "HashingEmbeddings",
    "OpenAICompatibleEmbeddings",
    "get_embedding_provider",
]
