from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="coursepilot-tests-"))
os.environ["APP_ENV"] = "test"
os.environ["SEED_DEMO"] = "false"
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DATA_DIR / 'test.db').as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["LLM_PROVIDER"] = "demo"

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client

