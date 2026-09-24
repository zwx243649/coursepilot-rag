from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Course, ImportJob
from app.schemas import ImportJobRead, WebImportRequest
from app.services.web_import import run_web_import


router = APIRouter(prefix="/api", tags=["imports"])


@router.post(
    "/courses/{course_id}/imports/web",
    response_model=ImportJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_web_import(
    course_id: str,
    payload: WebImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ImportJob:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")

    parsed = urlsplit(payload.url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Please provide a valid http(s) URL")

    job = ImportJob(
        course_id=course_id,
        root_url=payload.url.strip(),
        max_pages=payload.max_pages,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_web_import, job.id)
    return job


@router.get("/courses/{course_id}/imports", response_model=list[ImportJobRead])
def list_web_imports(
    course_id: str,
    db: Session = Depends(get_db),
) -> list[ImportJob]:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return list(
        db.scalars(
            select(ImportJob)
            .where(ImportJob.course_id == course_id)
            .order_by(ImportJob.created_at.desc())
            .limit(20)
        )
    )


@router.get("/imports/{job_id}", response_model=ImportJobRead)
def get_web_import(job_id: str, db: Session = Depends(get_db)) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job

