from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    color: str = Field(default="#0F766E", max_length=20)


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    color: str
    created_at: datetime
    document_count: int = 0
    chunk_count: int = 0


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    original_name: str
    mime_type: str
    status: str
    error_message: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class ChunkPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_index: int
    page_number: int | None
    content: str


class WebImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    max_pages: int = Field(default=12, ge=1, le=30)
    same_path_only: bool = True


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    root_url: str
    max_pages: int
    status: str
    discovered_count: int
    imported_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    course_id: str
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class Citation(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    document_name: str
    page_number: int | None
    score: float
    excerpt: str


class ChatTrace(BaseModel):
    nodes: list[str]
    decision: str
    retrieval_count: int
    latency_ms: int


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    citations: list[Citation]
    trace: ChatTrace


class ConversationMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    citations: list[dict]
    trace: dict | None
    created_at: datetime


class RelevantChunk(BaseModel):
    document: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)


class EvaluationCase(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_terms: list[str] = Field(default_factory=list)
    relevant: list[RelevantChunk] = Field(default_factory=list)
    answerable: bool = True


class EvaluationRequest(BaseModel):
    course_id: str
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)
    top_k: int = Field(default=5, ge=1, le=20)


class EvaluationCaseResult(BaseModel):
    question: str
    answerable: bool
    hit: bool
    reciprocal_rank: float
    recall_at_k: float
    precision_at_k: float
    ndcg_at_k: float
    term_coverage: float
    top_score: float
    latency_ms: int
    top_document: str | None
    decision: str
    passed: bool


class EvaluationResponse(BaseModel):
    hit_rate: float
    mrr: float
    recall_at_k: float
    precision_at_k: float
    ndcg_at_k: float
    average_term_coverage: float
    average_latency_ms: float
    decision_accuracy: float
    cases: list[EvaluationCaseResult]
