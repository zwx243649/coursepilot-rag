from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache

import httpx

from app.config import get_settings
from app.services.http_client import post_json


_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode("utf-8")).hexdigest()[:40]


def _load_cache(settings) -> dict[str, list[float]]:
    path = settings.embedding_cache_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(settings, cache: dict[str, list[float]]) -> None:
    """Best-effort persistence: a missing or read-only cache must not break a request."""
    path = settings.embedding_cache_path
    limit = settings.embedding_cache_max_entries
    if limit > 0 and len(cache) > limit:
        cache = {key: cache[key] for key in list(cache.keys())[-limit:]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cache), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


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
        if self.provider == "hash":
            return [hash_embedding(text, self.settings.embedding_dim) for text in texts]
        return self._remote_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _remote_embeddings(self, texts: list[str]) -> list[list[float]]:
        cache = (
            _load_cache(self.settings) if self.settings.embedding_cache_enabled else {}
        )
        vectors: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []

        for index, text in enumerate(texts):
            cached = cache.get(_cache_key(self.settings.embedding_model, text))
            if cached:
                vectors[index] = cached
            else:
                pending.append((index, text))

        for start in range(0, len(pending), self.settings.embedding_batch_size):
            batch = pending[start : start + self.settings.embedding_batch_size]
            batch_vectors = self._request_embeddings([text for _, text in batch])
            for (index, text), vector in zip(batch, batch_vectors, strict=True):
                vectors[index] = vector
                cache[_cache_key(self.settings.embedding_model, text)] = vector

        if pending and self.settings.embedding_cache_enabled:
            _save_cache(self.settings, cache)

        if any(vector is None for vector in vectors):
            raise RuntimeError("Embedding response did not cover every input")

        actual_dimension = len(vectors[0] or [])
        if actual_dimension != self.settings.embedding_dim:
            raise RuntimeError(
                "Embedding dimension mismatch: "
                f"model returned {actual_dimension}, "
                f"but EMBEDDING_DIM is {self.settings.embedding_dim}. "
                "Update EMBEDDING_DIM and use a new QDRANT_COLLECTION."
            )
        return [vector for vector in vectors if vector is not None]

    def _request_embeddings(self, batch: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {
            "model": self.settings.embedding_model,
            "input": batch,
            "encoding_format": "float",
        }
        if self.settings.embedding_send_dimensions:
            payload["dimensions"] = self.settings.embedding_dim
        try:
            response = post_json(
                f"{self.settings.embedding_base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.settings.embedding_api_key}"},
                payload=payload,
                timeout=self.settings.embedding_timeout_seconds,
                retries=self.settings.embedding_max_retries,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Embedding request failed: {exc}") from exc

        data = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding response count does not match input count")
        return vectors


@lru_cache
def get_embedder() -> EmbeddingService:
    return EmbeddingService()
