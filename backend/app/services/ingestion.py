from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete

from app.config import get_settings
from app.database import SessionLocal
from app.models import Chunk, Document, new_id, utc_now
from app.services.embeddings import get_embedder
from app.services.parsing import chunk_pages, extract_pages
from app.services.vector_store import get_vector_store


def ingest_document(document_id: str) -> None:
    settings = get_settings()
    session = SessionLocal()
    document = session.get(Document, document_id)
    if document is None:
        session.close()
        return

    try:
        document.status = "processing"
        document.error_message = None
        document.updated_at = utc_now()
        session.commit()

        path = Path(document.stored_path)
        pages = extract_pages(path, document.mime_type)
        chunks = chunk_pages(
            pages,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        if not chunks:
            raise ValueError("文件中没有可索引的文本内容")

        vectors = get_embedder().embed_documents([chunk.content for chunk in chunks])
        vector_store = get_vector_store()
        vector_store.delete_by_document(document.course_id, document.id)

        points = []
        chunk_models = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk_id = new_id()
            payload = {
                "chunk_id": chunk_id,
                "course_id": document.course_id,
                "document_id": document.id,
                "document_name": document.original_name,
                "page_number": chunk.page_number,
                "section": chunk.section,
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
            }
            points.append({"id": chunk_id, "vector": vector, "payload": payload})
            chunk_models.append(
                Chunk(
                    id=chunk_id,
                    document_id=document.id,
                    course_id=document.course_id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    content=chunk.content,
                    vector_id=chunk_id,
                )
            )

        vector_store.upsert(document.course_id, points)
        session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        session.add_all(chunk_models)
        document.chunk_count = len(chunk_models)
        document.status = "ready"
        document.updated_at = utc_now()
        session.commit()
    except Exception as exc:
        session.rollback()
        document = session.get(Document, document_id)
        if document is not None:
            document.status = "failed"
            document.error_message = str(exc)[:1000]
            document.updated_at = utc_now()
            session.commit()
    finally:
        session.close()
