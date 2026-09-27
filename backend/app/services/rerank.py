from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.services.http_client import post_json
from app.services.vector_store import VectorHit


logger = logging.getLogger(__name__)


class RerankService:
    """Cross-encoder style reranking through the DashScope text-rerank API."""

    def __init__(self) -> None:
        self.settings = get_settings()
        # Telemetry for degraded mode: reranking is best-effort, so the last
        # failure is surfaced through /api/system/health instead of being lost.
        self.last_error: str | None = None

    @property
    def provider(self) -> str:
        if (
            self.settings.rerank_enabled
            and self.settings.rerank_provider == "dashscope"
            and self.settings.rerank_api_key
        ):
            return "dashscope"
        return "none"

    def rerank(self, query: str, hits: list[VectorHit], top_n: int) -> list[VectorHit]:
        """Return at most `top_n` hits ordered by rerank score.

        Failures fall back to the retrieval order: reranking is an optimisation,
        not a hard dependency, so a provider outage must not break answering.
        """
        if self.provider == "none" or len(hits) <= 1:
            return hits[:top_n]

        payload = {
            "model": self.settings.rerank_model,
            "input": {
                "query": query,
                "documents": [
                    str(hit.payload.get("content", "")) for hit in hits
                ],
            },
            "parameters": {
                "return_documents": False,
                "top_n": min(top_n, len(hits)),
            },
        }
        try:
            response = post_json(
                self.settings.rerank_base_url,
                headers={
                    "Authorization": f"Bearer {self.settings.rerank_api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout=self.settings.rerank_timeout_seconds,
                retries=self.settings.rerank_max_retries,
            )
            response.raise_for_status()
            results = response.json()["output"]["results"]
        except Exception:
            logger.warning("rerank request failed (%s), falling back to retrieval order", self.settings.rerank_model, exc_info=True)
            self.last_error = "rerank request failed"
            return hits[:top_n]

        self.last_error = None
        ordered: list[VectorHit] = []
        seen: set[int] = set()
        for item in sorted(results, key=lambda row: row["relevance_score"], reverse=True):
            index = int(item["index"])
            if index in seen or not 0 <= index < len(hits):
                continue
            seen.add(index)
            hit = hits[index]
            hit.rerank_score = float(item["relevance_score"])
            ordered.append(hit)

        for index, hit in enumerate(hits):
            if index not in seen:
                ordered.append(hit)
        return ordered[:top_n]


@lru_cache
def get_reranker() -> RerankService:
    return RerankService()
