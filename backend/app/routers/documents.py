from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Chunk, Course, Document, new_id
from app.schemas import ChunkPreview, DocumentRead
from app.services.ingestion import ingest_document
from app.services.vector_store import get_vector_store


router = APIRouter(prefix="/api", tags=["documents"])
ALLOWED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}


def _get_document_or_404(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/courses/{course_id}/documents", response_model=list[DocumentRead])
def list_documents(course_id: str, db: Session = Depends(get_db)) -> list[Document]:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return list(
        db.scalars(
            select(Document)
            .where(Document.course_id == course_id)
            .order_by(Document.created_at.desc())
        )
    )


@router.post(
    "/courses/{course_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    course_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Document:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")

    original_name = Path(file.filename or "untitled.txt").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, Markdown, and plain text files are supported",
        )

    settings = get_settings()
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_upload_mb} MB",
        )
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    document_id = new_id()
    stored_path = settings.upload_dir / f"{document_id}{suffix}"
    stored_path.write_bytes(content)

    document = Document(
        id=document_id,
        course_id=course_id,
        original_name=original_name,
        stored_path=str(stored_path),
        mime_type=file.content_type or "application/octet-stream",
        status="queued",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(ingest_document, document.id)
    return document


@router.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: str, db: Session = Depends(get_db)) -> Document:
    return _get_document_or_404(db, document_id)


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkPreview])
def get_document_chunks(
    document_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[Chunk]:
    _get_document_or_404(db, document_id)
    return list(
        db.scalars(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index.asc())
            .limit(max(1, min(limit, 200)))
        )
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    document = _get_document_or_404(db, document_id)
    get_vector_store().delete_by_document(document.course_id, document.id)
    stored_path = Path(document.stored_path)
    db.delete(document)
    db.commit()
    if stored_path.exists():
        stored_path.unlink(missing_ok=True)

