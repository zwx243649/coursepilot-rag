from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    seed_demo: bool
    database_url: str
    data_dir: Path
    upload_dir: Path
    frontend_dir: Path | None

    vector_backend: str
    qdrant_url: str
    qdrant_api_key: str | None
    qdrant_collection: str

    embedding_provider: str
    embedding_base_url: str
    embedding_api_key: str | None
    embedding_model: str
    embedding_dim: int
    embedding_batch_size: int
    embedding_send_dimensions: bool

    embedding_cache_enabled: bool
    embedding_cache_path: Path
    embedding_cache_max_entries: int
    embedding_max_retries: int
    embedding_timeout_seconds: float

    llm_provider: str
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str

    rerank_enabled: bool
    rerank_provider: str
    rerank_base_url: str
    rerank_api_key: str | None
    rerank_model: str
    rerank_timeout_seconds: float
    rerank_max_retries: int
    query_rewrite_enabled: bool

    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int
    retrieval_candidates: int
    hybrid_retrieval_enabled: bool
    min_retrieval_score: float
    max_upload_mb: int
    cors_origins: tuple[str, ...]

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    upload_dir = data_dir / "uploads"
    default_frontend = Path(__file__).resolve().parents[2] / "frontend"
    frontend_dir = Path(os.getenv("FRONTEND_DIR", str(default_frontend))).resolve()
    origins = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if item.strip()
    )

    settings = Settings(
        app_name="CoursePilot",
        app_env=os.getenv("APP_ENV", "development"),
        seed_demo=_env_bool("SEED_DEMO", True),
        database_url=os.getenv(
            "DATABASE_URL",
            f"sqlite:///{(data_dir / 'coursepilot.db').as_posix()}",
        ),
        data_dir=data_dir,
        upload_dir=upload_dir,
        frontend_dir=frontend_dir if frontend_dir.exists() else None,
        vector_backend=os.getenv("VECTOR_BACKEND", "local").strip().lower(),
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "coursepilot_chunks"),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "hash").strip().lower(),
        embedding_base_url=os.getenv(
            "EMBEDDING_BASE_URL",
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        ).rstrip("/"),
        embedding_api_key=(
            os.getenv("EMBEDDING_API_KEY")
            or os.getenv("LLM_API_KEY")
            or None
        ),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "384")),
        embedding_batch_size=max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))),
        embedding_send_dimensions=_env_bool("EMBEDDING_SEND_DIMENSIONS", False),
        embedding_cache_enabled=_env_bool("EMBEDDING_CACHE_ENABLED", True),
        embedding_cache_path=Path(
            os.getenv("EMBEDDING_CACHE_PATH", str(data_dir / "embedding_cache.json"))
        ).resolve(),
        embedding_cache_max_entries=max(
            0, int(os.getenv("EMBEDDING_CACHE_MAX_ENTRIES", "2000"))
        ),
        embedding_max_retries=max(1, int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))),
        embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30")),
        llm_provider=os.getenv("LLM_PROVIDER", "demo").strip().lower(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        rerank_enabled=_env_bool("RERANK_ENABLED", True),
        rerank_provider=os.getenv("RERANK_PROVIDER", "dashscope").strip().lower(),
        rerank_base_url=os.getenv(
            "RERANK_BASE_URL",
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        ),
        rerank_api_key=(
            os.getenv("RERANK_API_KEY") or os.getenv("LLM_API_KEY") or None
        ),
        rerank_model=os.getenv("RERANK_MODEL", "gte-rerank-v2"),
        rerank_timeout_seconds=float(os.getenv("RERANK_TIMEOUT_SECONDS", "25")),
        rerank_max_retries=max(1, int(os.getenv("RERANK_MAX_RETRIES", "2"))),
        query_rewrite_enabled=_env_bool("QUERY_REWRITE_ENABLED", True),
        chunk_size=int(os.getenv("CHUNK_SIZE", "700")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "100")),
        retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "6")),
        retrieval_candidates=max(1, int(os.getenv("RETRIEVAL_CANDIDATES", "20"))),
        hybrid_retrieval_enabled=_env_bool("HYBRID_RETRIEVAL_ENABLED", True),
        min_retrieval_score=float(os.getenv("MIN_RETRIEVAL_SCORE", "0.45")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "25")),
        cors_origins=origins,
    )
    settings.ensure_directories()
    return settings
