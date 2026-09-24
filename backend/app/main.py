from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import seed_demo_data
from app.config import get_settings
from app.database import init_db
from app.routers import chat, courses, documents, evaluations, imports, system


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_demo_data()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(evaluations.router)
app.include_router(imports.router)
app.include_router(system.router)


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}


if settings.frontend_dir is not None:
    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(settings.frontend_dir / "index.html")

    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dir, html=True),
        name="frontend",
    )
