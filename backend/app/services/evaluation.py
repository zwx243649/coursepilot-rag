from __future__ import annotations

import math
import time

from app.config import get_settings
from app.schemas import EvaluationCase, EvaluationCaseResult, EvaluationResponse
from app.services.agent import decide
from app.services.embeddings import get_embedder
from app.services.vector_store import VectorHit, get_vector_store


def _hit_key(hit: VectorHit) -> tuple[str, int] | None:
    payload = hit.payload
    document = payload.get("document_name")
    chunk_index = payload.get("chunk_index")
    if document is None or chunk_index is None:
        return None
    return (str(document), int(chunk_index))


def _ndcg(relevances: list[int]) -> float:
    if not relevances:
        return 0.0
    dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevances, start=1))
    ideal = sorted(relevances, reverse=True)
    idcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def _relevance_flags(
    case: EvaluationCase,
    hits: list[VectorHit],
) -> tuple[list[int], int]:
    """Per-rank relevance flags plus the number of relevant chunks in the corpus.

    Ground truth comes from the annotated `relevant` chunks. When a case has no
    annotation (for example a question typed straight into the UI), relevance
    falls back to keyword matching so the metrics stay usable.
    """
    expected = [term.strip().lower() for term in case.expected_terms if term.strip()]
    annotated = {(item.document, int(item.chunk_index)) for item in case.relevant}

    if annotated:
        flags = [1 if key in annotated else 0 for key in (_hit_key(hit) for hit in hits)]
        return flags, len(annotated)

    flags = []
    for hit in hits:
        content = str(hit.payload.get("content", "")).lower()
        flags.append(1 if any(term in content for term in expected) else 0)
    return flags, max(sum(flags), 1) if expected else len(hits)


def run_evaluation(
    course_id: str,
    cases: list[EvaluationCase],
    top_k: int,
) -> EvaluationResponse:
    settings = get_settings()
    embedder = get_embedder()
    vector_store = get_vector_store()
    provider = embedder.provider

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
        flags, total_relevant = _relevance_flags(case, hits)
        retrieved_relevant = sum(flags)

        first_relevant_rank = next(
            (rank for rank, flag in enumerate(flags, start=1) if flag),
            0,
        )
        best_coverage = 0.0
        for hit in hits:
            content = str(hit.payload.get("content", "")).lower()
            covered = sum(1 for term in expected if term in content)
            coverage = covered / len(expected) if expected else (1.0 if hits else 0.0)
            best_coverage = max(best_coverage, coverage)

        decision = decide(hits, provider, settings.min_retrieval_score)
        passed = decision == ("generate" if case.answerable else "refuse")

        results.append(
            EvaluationCaseResult(
                question=case.question,
                answerable=case.answerable,
                hit=first_relevant_rank > 0,
                reciprocal_rank=(1.0 / first_relevant_rank) if first_relevant_rank else 0.0,
                recall_at_k=(retrieved_relevant / total_relevant) if total_relevant else 0.0,
                precision_at_k=(retrieved_relevant / len(flags)) if flags else 0.0,
                ndcg_at_k=_ndcg(flags),
                term_coverage=best_coverage,
                top_score=hits[0].score if hits else 0.0,
                latency_ms=latency_ms,
                top_document=(
                    str(hits[0].payload.get("document_name"))
                    if hits and hits[0].payload.get("document_name")
                    else None
                ),
                decision=decision,
                passed=passed,
            )
        )

    # Retrieval metrics only make sense for answerable cases; decision accuracy
    # covers both answerable and unanswerable ones.
    answerable = [r for r, case in zip(results, cases, strict=True) if case.answerable]
    retrieval_sample = answerable or results
    sample_size = len(retrieval_sample)

    return EvaluationResponse(
        hit_rate=sum(1 for item in retrieval_sample if item.hit) / sample_size,
        mrr=sum(item.reciprocal_rank for item in retrieval_sample) / sample_size,
        recall_at_k=sum(item.recall_at_k for item in retrieval_sample) / sample_size,
        precision_at_k=sum(item.precision_at_k for item in retrieval_sample) / sample_size,
        ndcg_at_k=sum(item.ndcg_at_k for item in retrieval_sample) / sample_size,
        average_term_coverage=(
            sum(item.term_coverage for item in retrieval_sample) / sample_size
        ),
        average_latency_ms=sum(item.latency_ms for item in results) / len(results),
        decision_accuracy=sum(1 for item in results if item.passed) / len(results),
        cases=results,
    )
