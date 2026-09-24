from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Chunk, Course, Document
from app.schemas import CourseCreate, CourseRead
from app.services.vector_store import get_vector_store


router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[CourseRead]:
    statement = (
        select(
            Course,
            func.count(distinct(Document.id)).label("document_count"),
            func.count(distinct(Chunk.id)).label("chunk_count"),
        )
        .outerjoin(Document, Document.course_id == Course.id)
        .outerjoin(Chunk, Chunk.course_id == Course.id)
        .group_by(Course.id)
        .order_by(Course.created_at.asc())
    )
    rows = db.execute(statement).all()
    return [
        CourseRead(
            id=course.id,
            name=course.name,
            description=course.description,
            color=course.color,
            created_at=course.created_at,
            document_count=document_count,
            chunk_count=chunk_count,
        )
        for course, document_count, chunk_count in rows
    ]


@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> CourseRead:
    course = Course(
        name=payload.name.strip(),
        description=payload.description.strip(),
        color=payload.color,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return CourseRead.model_validate(course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: str, db: Session = Depends(get_db)) -> None:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    vector_store = get_vector_store()
    for document in course.documents:
        vector_store.delete_by_document(course.id, document.id)
    db.delete(course)
    db.commit()

