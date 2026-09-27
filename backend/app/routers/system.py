from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import database_is_healthy, get_db
from app.models import Chunk, Course, Document
from app.services.embeddings import get_embedder
from app.services.ingestion import ingest_document
from app.services.llm import get_llm
from app.services.rerank import get_reranker
from app.services.vector_store import get_vector_store


router = APIRouter(prefix="/api/system", tags=["system"])


def _reindex_documents(document_ids: list[str]) -> None:
    for document_id in document_ids:
        ingest_document(document_id)


@router.get("/health")
def health() -> dict:
    vector_store = get_vector_store()
    return {
        "status": "ok" if database_is_healthy() and vector_store.health() else "degraded",
        "database": database_is_healthy(),
        "vector_store": vector_store.health(),
        "embedding_provider": get_embedder().provider,
        "llm": get_llm().health(),
        "rerank": {
            "provider": get_reranker().provider,
            "model": get_settings().rerank_model,
            "last_error": get_reranker().last_error,
        },
    }


@router.get("/info")
def system_info(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    return {
        "app": settings.app_name,
        "environment": settings.app_env,
        "embedding": {
            "provider": get_embedder().provider,
            "base_url": settings.embedding_base_url,
            "model": settings.embedding_model,
            "dimension": settings.embedding_dim,
            "batch_size": settings.embedding_batch_size,
        },
        "llm": get_llm().health(),
        "retrieval": {
            "top_k": settings.retrieval_top_k,
            "candidates": settings.retrieval_candidates,
            "hybrid_enabled": settings.hybrid_retrieval_enabled,
            "query_rewrite_enabled": settings.query_rewrite_enabled,
            "rerank": {
                "provider": get_reranker().provider,
                "model": settings.rerank_model,
            },
        },
        "vector_store": get_vector_store().info(),
        "counts": {
            "courses": db.scalar(select(func.count(Course.id))) or 0,
            "documents": db.scalar(select(func.count(Document.id))) or 0,
            "chunks": db.scalar(select(func.count(Chunk.id))) or 0,
        },
    }


@router.post("/reindex", status_code=202)
def reindex_all_documents(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    document_ids = list(db.scalars(select(Document.id).order_by(Document.created_at.asc())))
    background_tasks.add_task(_reindex_documents, document_ids)
    return {
        "status": "queued",
        "document_count": len(document_ids),
        "embedding_provider": get_embedder().provider,
        "embedding_model": get_settings().embedding_model,
    }
