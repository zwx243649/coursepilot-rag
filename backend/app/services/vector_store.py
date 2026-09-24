from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import get_settings
from app.services.embeddings import _hash_tokens


@dataclass(slots=True)
class VectorHit:
    chunk_id: str
    score: float
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "score": self.score, "payload": self.payload}


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return product / (left_norm * right_norm)


def _lexical_score(query: str, content: str) -> float:
    query_tokens = {token for token, _ in _hash_tokens(query)}
    if not query_tokens:
        return 0.0
    content_tokens = {token for token, _ in _hash_tokens(content)}
    return len(query_tokens & content_tokens) / len(query_tokens)


class LocalVectorStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._data, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def upsert(
        self,
        course_id: str,
        points: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            course_points = self._data.setdefault(course_id, {})
            for point in points:
                course_points[point["id"]] = {
                    "vector": point["vector"],
                    "payload": point["payload"],
                }
            self._save()

    def search(
        self,
        course_id: str,
        vector: list[float],
        limit: int,
        query: str = "",
    ) -> list[VectorHit]:
        with self._lock:
            points = self._data.get(course_id, {})
            scored: list[VectorHit] = []
            for point_id, point in points.items():
                semantic = _cosine(vector, point["vector"])
                content = str(point["payload"].get("content", ""))
                lexical = _lexical_score(query, content)
                score = semantic * 0.8 + lexical * 0.2
                scored.append(
                    VectorHit(
                        chunk_id=point_id,
                        score=max(0.0, min(1.0, score)),
                        payload=point["payload"],
                    )
                )
            scored.sort(key=lambda item: item.score, reverse=True)
            return scored[:limit]

    def delete_by_document(self, course_id: str, document_id: str) -> None:
        with self._lock:
            course_points = self._data.get(course_id, {})
            for point_id in [
                point_id
                for point_id, point in course_points.items()
                if point["payload"].get("document_id") == document_id
            ]:
                del course_points[point_id]
            self._save()

    def health(self) -> bool:
        return True

    def info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend": "local",
                "courses": len(self._data),
                "points": sum(len(points) for points in self._data.values()),
            }


class QdrantVectorStore:
    def __init__(
        self,
        url: str,
        api_key: str | None,
        collection: str,
        dimension: int,
    ) -> None:
        self.collection = collection
        self.dimension = dimension
        self.client = QdrantClient(url=url, api_key=api_key, timeout=20.0)

    def ensure_ready(self) -> None:
        collections = {
            item.name for item in self.client.get_collections().collections
        }
        if self.collection not in collections:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.dimension,
                    distance=Distance.COSINE,
                ),
            )

    def upsert(self, course_id: str, points: list[dict[str, Any]]) -> None:
        self.ensure_ready()
        qdrant_points = [
            PointStruct(
                id=point["id"],
                vector=point["vector"],
                payload={**point["payload"], "course_id": course_id},
            )
            for point in points
        ]
        if qdrant_points:
            self.client.upsert(
                collection_name=self.collection,
                points=qdrant_points,
                wait=True,
            )

    def search(
        self,
        course_id: str,
        vector: list[float],
        limit: int,
        query: str = "",
    ) -> list[VectorHit]:
        self.ensure_ready()
        course_filter = Filter(
            must=[
                FieldCondition(
                    key="course_id",
                    match=MatchValue(value=course_id),
                )
            ]
        )
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=course_filter,
            limit=limit,
            with_payload=True,
        )
        points = response.points
        return [
            VectorHit(
                chunk_id=str(point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in points
        ]

    def delete_by_document(self, course_id: str, document_id: str) -> None:
        self.ensure_ready()
        selector = Filter(
            must=[
                FieldCondition(
                    key="course_id",
                    match=MatchValue(value=course_id),
                ),
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                ),
            ]
        )
        self.client.delete(
            collection_name=self.collection,
            points_selector=selector,
            wait=True,
        )

    def health(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def info(self) -> dict[str, Any]:
        try:
            collection = self.client.get_collection(self.collection)
            return {
                "backend": "qdrant",
                "points": collection.points_count,
                "status": str(collection.status),
            }
        except Exception:
            return {"backend": "qdrant", "points": None, "status": "unavailable"}


@lru_cache
def get_vector_store() -> LocalVectorStore | QdrantVectorStore:
    settings = get_settings()
    if settings.vector_backend == "qdrant":
        return QdrantVectorStore(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.qdrant_collection,
            dimension=settings.embedding_dim,
        )
    return LocalVectorStore(settings.data_dir / "local_vectors.json")

