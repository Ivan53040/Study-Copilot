"""Embedding providers.

``OpenAICompatibleEmbeddings`` talks to LM Studio's (or any OpenAI-compatible)
``/embeddings`` endpoint. ``HashingEmbeddings`` is a deterministic, dependency-
free fallback so retrieval is testable offline and the app still works when no
embedding model is loaded — similarity is crude (shared-token overlap) but real.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

import httpx

from app.config.settings import Settings
from app.logging_config import get_logger

logger = get_logger("embeddings")

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@runtime_checkable
class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


class HashingEmbeddings:
    """Deterministic bag-of-hashed-tokens embedding (offline fallback/tests)."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.model_name = f"hash-{dim}"

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN_RE.findall(text.lower()):
            h = int.from_bytes(
                hashlib.md5(tok.encode("utf-8")).digest()[:4], "little"
            )
            idx = h % self.dim
            sign = 1.0 if (h >> 31) & 1 else -1.0
            vec[idx] += sign
        return _l2_normalize(vec)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OpenAICompatibleEmbeddings:
    """Calls an OpenAI-compatible /embeddings endpoint (e.g. LM Studio)."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        resp = httpx.post(
            url,
            json={"model": self.model_name, "input": texts},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # Preserve input order (responses include an index).
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        return [item["embedding"] for item in ordered]


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    cfg = settings.embeddings
    if cfg.provider == "hash":
        return HashingEmbeddings(dim=cfg.hash_dim)
    base_url = cfg.base_url or settings.models.lmstudio.base_url
    return OpenAICompatibleEmbeddings(base_url=base_url, model=cfg.model)
