from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.services.http_client import post_json
from app.services.vector_store import VectorHit, _rrf_fuse


logger = logging.getLogger(__name__)


class RerankService:
    """Cross-encoder style reranking.

    Two request shapes are supported because providers disagree on the payload:
    DashScope nests the query under `input` and returns `output.results`, while
    SiliconFlow (and other OpenAI-style rerank APIs) put `query`/`documents` at
    the top level and return `results`.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        # Telemetry for degraded mode: reranking is best-effort, so the last
        # failure is surfaced through /api/system/health instead of being lost.
        self.last_error: str | None = None

    @property
    def provider(self) -> str:
        if not self.settings.rerank_enabled or not self.settings.rerank_api_key:
            return "none"
        if self.settings.rerank_provider in {"dashscope", "siliconflow"}:
            return self.settings.rerank_provider
        return "none"

    def _request_spec(
        self,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> tuple[dict, callable]:
        if self.provider == "dashscope":
            payload = {
                "model": self.settings.rerank_model,
                "input": {"query": query, "documents": documents},
                "parameters": {"return_documents": False, "top_n": top_n},
            }

            def extract(data: dict) -> list[tuple[int, float]]:
                return [
                    (int(item["index"]), float(item["relevance_score"]))
                    for item in data["output"]["results"]
                ]

            return payload, extract

        payload = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }

        def extract_flat(data: dict) -> list[tuple[int, float]]:
            return [
                (int(item["index"]), float(item["relevance_score"]))
                for item in data["results"]
            ]

        return payload, extract_flat

    def rerank(self, query: str, hits: list[VectorHit], top_n: int) -> list[VectorHit]:
        return self.rerank_multi([query], hits, top_n)

    def rerank_multi(
        self,
        queries: list[str],
        hits: list[VectorHit],
        top_n: int,
    ) -> list[VectorHit]:
        """Rerank with one or more queries and fuse their rankings.

        Query rewriting makes the retrieval query more English while the source
        material may be Chinese (or the other way round), so neither query alone
        is right for every document. Each query scores the same candidate set and
        the rankings are fused with RRF, which lets a document surface when either
        query considers it relevant.
        """
        if self.provider == "none" or len(hits) <= 1:
            return hits[:top_n]

        per_query: list[dict[int, float]] = []
        for query in queries:
            scores = self._score(query, hits, top_n)
            per_query.append(dict(scores) if scores is not None else {})

        if all(not scores for scores in per_query):
            return hits[:top_n]

        # Fuse the per-query rankings with reciprocal rank fusion: a candidate
        # that either query ranks highly comes up, and no single query language
        # is forced onto documents written in the other language.
        rankings = [
            [
                index
                for index, _ in sorted(scores.items(), key=lambda row: row[1], reverse=True)
            ]
            for scores in per_query
            if scores
        ]
        order = _rrf_fuse(rankings)

        best: dict[int, float] = {}
        for index in order:
            scores = [
                per_query[position][index]
                for position in range(len(per_query))
                if index in per_query[position]
            ]
            if scores:
                best[index] = max(scores)
        for index, score in best.items():
            hits[index].rerank_score = score
        return [hits[index] for index in order][:top_n]

    def _score(
        self,
        query: str,
        hits: list[VectorHit],
        top_n: int,
    ) -> list[tuple[int, float]] | None:
        """Score every candidate for one query; None means the call failed.

        Reranking is an optimisation, not a hard dependency: a provider outage
        must not break answering, so callers fall back to the retrieval order.
        """
        documents = [str(hit.payload.get("content", "")) for hit in hits]
        payload, extract = self._request_spec(query, documents, min(top_n, len(hits)))
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
            results = extract(response.json())
        except Exception:
            logger.warning("rerank request failed (%s), falling back to retrieval order", self.settings.rerank_model, exc_info=True)
            self.last_error = "rerank request failed"
            return None

        self.last_error = None
        return [
            (index, score)
            for index, score in results
            if 0 <= index < len(hits)
        ]


@lru_cache
def get_reranker() -> RerankService:
    return RerankService()
