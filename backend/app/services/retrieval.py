from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.embeddings import get_embedder
from app.services.llm import get_llm
from app.services.rerank import get_reranker
from app.services.vector_store import VectorHit, get_vector_store


class RetrievalService:
    """The single retrieval pipeline used by both the agent and the evaluation.

    查询改写（可选）→ 向量化 → 混合召回（稠密 + BM25，RRF 融合）→ 重排（可选）。
    Keeping one implementation means the benchmark measures what production runs.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedder = get_embedder()
        self.vector_store = get_vector_store()
        self.reranker = get_reranker()
        self.llm = get_llm()

    def rewrite_query(self, question: str) -> tuple[str, bool]:
        if not self.settings.query_rewrite_enabled:
            return question, False
        rewritten = self.llm.rewrite_query(question)
        if rewritten and rewritten.strip():
            return rewritten.strip(), True
        return question, False

    def retrieve(
        self,
        course_id: str,
        query: str,
        top_k: int | None = None,
        rewrite: bool = False,
    ) -> tuple[list[VectorHit], dict]:
        limit = top_k or self.settings.retrieval_top_k
        candidates = max(limit, self.settings.retrieval_candidates)

        rewritten = False
        if rewrite:
            query, rewritten = self.rewrite_query(query)

        vector = self.embedder.embed_query(query)
        hits = self.vector_store.search(
            course_id=course_id,
            vector=vector,
            limit=candidates,
            query=query,
        )

        reranked = False
        if hits and self.reranker.provider != "none":
            hits = self.reranker.rerank(query, hits, limit)
            reranked = True
        else:
            hits = hits[:limit]

        meta = {
            "candidates": candidates,
            "reranked": reranked,
            "rewritten": rewritten,
            "query": query,
            "returned": len(hits),
        }
        return hits, meta


@lru_cache
def get_retrieval_service() -> RetrievalService:
    return RetrievalService()
