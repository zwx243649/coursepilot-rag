from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

import httpx

from app.config import get_settings


_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")


def _hash_tokens(text: str) -> list[tuple[str, float]]:
    normalized = text.lower()
    tokens: list[tuple[str, float]] = []

    for word in _WORD_RE.findall(normalized):
        tokens.append((word, 1.0))

    for run in _CJK_RE.findall(normalized):
        chars = list(run)
        tokens.extend((char, 0.7) for char in chars)
        tokens.extend((run[index : index + 2], 1.2) for index in range(len(run) - 1))

    return tokens


def hash_embedding(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    for token, base_weight in _hash_tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * base_weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def provider(self) -> str:
        remote_providers = {"openai", "openai-compatible", "bge", "qwen"}
        if (
            self.settings.embedding_provider in remote_providers
            and self.settings.embedding_api_key
        ):
            return self.settings.embedding_provider
        return "hash"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.provider != "hash":
            return self._openai_compatible_embeddings(texts)
        return [hash_embedding(text, self.settings.embedding_dim) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _openai_compatible_embeddings(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.settings.embedding_api_key}"}
        vectors: list[list[float]] = []
        batch_size = self.settings.embedding_batch_size
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            payload: dict[str, object] = {
                "model": self.settings.embedding_model,
                "input": batch,
                "encoding_format": "float",
            }
            if self.settings.embedding_send_dimensions:
                payload["dimensions"] = self.settings.embedding_dim
            try:
                response = httpx.post(
                    f"{self.settings.embedding_base_url}/embeddings",
                    headers=headers,
                    json=payload,
                    timeout=120.0,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Embedding request failed: {exc}") from exc

            data = sorted(response.json()["data"], key=lambda item: item["index"])
            batch_vectors = [item["embedding"] for item in data]
            if len(batch_vectors) != len(batch):
                raise RuntimeError("Embedding response count does not match input count")
            vectors.extend(batch_vectors)

        actual_dimension = len(vectors[0]) if vectors else 0
        if actual_dimension != self.settings.embedding_dim:
            raise RuntimeError(
                "Embedding dimension mismatch: "
                f"model returned {actual_dimension}, "
                f"but EMBEDDING_DIM is {self.settings.embedding_dim}. "
                "Update EMBEDDING_DIM and use a new QDRANT_COLLECTION."
            )
        return vectors


@lru_cache
def get_embedder() -> EmbeddingService:
    return EmbeddingService()
