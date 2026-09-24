from __future__ import annotations

import time

from app.config import get_settings
from app.schemas import EvaluationCase, EvaluationCaseResult, EvaluationResponse
from app.services.embeddings import get_embedder
from app.services.vector_store import get_vector_store


def run_evaluation(course_id: str, cases: list[EvaluationCase], top_k: int) -> EvaluationResponse:
    embedder = get_embedder()
    vector_store = get_vector_store()
    results: list[EvaluationCaseResult] = []

    for case in cases:
        started = time.perf_counter()
        vector = embedder.embed_query(case.question)
        hits = vector_store.search(
            course_id=course_id,
            vector=vector,
            limit=top_k,
            query=case.question,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        expected = [term.strip().lower() for term in case.expected_terms if term.strip()]
        first_relevant_rank = 0
        best_coverage = 0.0

        for rank, hit in enumerate(hits, start=1):
            content = str(hit.payload.get("content", "")).lower()
            covered = sum(1 for term in expected if term in content)
            coverage = covered / len(expected) if expected else (1.0 if hits else 0.0)
            best_coverage = max(best_coverage, coverage)
            if coverage > 0 and first_relevant_rank == 0:
                first_relevant_rank = rank

        hit = bool(hits) if not expected else first_relevant_rank > 0
        result = EvaluationCaseResult(
            question=case.question,
            hit=hit,
            reciprocal_rank=(1.0 / first_relevant_rank) if first_relevant_rank else 0.0,
            term_coverage=best_coverage,
            top_score=hits[0].score if hits else 0.0,
            latency_ms=latency_ms,
            top_document=(
                str(hits[0].payload.get("document_name"))
                if hits and hits[0].payload.get("document_name")
                else None
            ),
        )
        results.append(result)

    count = len(results)
    return EvaluationResponse(
        hit_rate=sum(1 for item in results if item.hit) / count,
        mrr=sum(item.reciprocal_rank for item in results) / count,
        average_term_coverage=sum(item.term_coverage for item in results) / count,
        average_latency_ms=sum(item.latency_ms for item in results) / count,
        cases=results,
    )

