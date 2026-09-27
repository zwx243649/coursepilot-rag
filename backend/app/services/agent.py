from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, TypedDict

from app.config import get_settings
from app.services.embeddings import get_embedder
from app.services.llm import get_llm
from app.services.retrieval import get_retrieval_service
from app.services.vector_store import VectorHit, get_vector_store

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - exercised only in minimal installs
    END = START = StateGraph = None


def effective_threshold(provider: str, configured: float) -> float:
    """Hash vectors score lower overall, so they get their own gate."""
    return 0.05 if provider == "hash" else configured


def decide(hits: list[VectorHit], provider: str, configured: float) -> str:
    """Single source of truth for the generate/refuse decision.

    Uses the best retrieval score among the returned hits rather than the head of
    the list, so reranking can reorder candidates without moving the gate.
    """
    best_score = max((hit.score for hit in hits), default=0.0)
    if hits and best_score >= effective_threshold(provider, configured):
        return "generate"
    return "refuse"


class AgentState(TypedDict, total=False):
    course_id: str
    question: str
    search_query: str
    rewrite_applied: bool
    hits: list[dict[str, Any]]
    retrieval_meta: dict[str, Any]
    answer: str
    decision: str
    trace_nodes: list[str]
    error: str


def _clean_query(question: str) -> str:
    rewritten = re.sub(r"^(请问|请帮我|帮我|你能|能不能)\s*", "", question.strip())
    return rewritten or question.strip()


class CoursePilotAgent:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedder = get_embedder()
        self.vector_store = get_vector_store()
        self.llm = get_llm()
        self.retrieval = get_retrieval_service()
        self.graph = self._build_graph()

    def _build_graph(self):
        if StateGraph is None:
            return None

        workflow = StateGraph(AgentState)
        workflow.add_node("analyze", self._analyze)
        workflow.add_node("rewrite", self._rewrite)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("grade", self._grade)
        workflow.add_node("generate", self._generate)
        workflow.add_node("refuse", self._refuse)

        workflow.add_edge(START, "analyze")
        workflow.add_edge("analyze", "rewrite")
        workflow.add_edge("rewrite", "retrieve")
        workflow.add_edge("retrieve", "grade")
        workflow.add_conditional_edges(
            "grade",
            lambda state: state["decision"],
            {
                "generate": "generate",
                "refuse": "refuse",
            },
        )
        workflow.add_edge("generate", END)
        workflow.add_edge("refuse", END)
        return workflow.compile()

    def run(self, course_id: str, question: str) -> AgentState:
        initial: AgentState = {
            "course_id": course_id,
            "question": question,
            "trace_nodes": [],
        }
        if self.graph is not None:
            return self.graph.invoke(initial)

        state = self._analyze(initial)
        state = self._rewrite(state)
        state = self._retrieve(state)
        state = self._grade(state)
        if state["decision"] == "generate":
            return self._generate(state)
        return self._refuse(state)

    def _analyze(self, state: AgentState) -> AgentState:
        state["search_query"] = _clean_query(state["question"])
        state["trace_nodes"] = [*state.get("trace_nodes", []), "analyze"]
        return state

    def _rewrite(self, state: AgentState) -> AgentState:
        query, applied = self.retrieval.rewrite_query(state["search_query"])
        state["search_query"] = query
        state["rewrite_applied"] = applied
        state["trace_nodes"] = [*state.get("trace_nodes", []), "rewrite"]
        return state

    def _retrieve(self, state: AgentState) -> AgentState:
        hits, meta = self.retrieval.retrieve(
            state["course_id"],
            state["search_query"],
        )
        state["hits"] = [hit.as_dict() for hit in hits]
        state["retrieval_meta"] = meta
        state["trace_nodes"] = [*state.get("trace_nodes", []), "retrieve"]
        return state

    def _grade(self, state: AgentState) -> AgentState:
        hits = state.get("hits", [])
        typed_hits = [
            VectorHit(
                chunk_id=item["chunk_id"],
                score=float(item["score"]),
                payload=item["payload"],
            )
            for item in hits
        ]
        state["decision"] = decide(
            typed_hits,
            self.embedder.provider,
            self.settings.min_retrieval_score,
        )
        state["trace_nodes"] = [*state.get("trace_nodes", []), "grade"]
        return state

    def _generate(self, state: AgentState) -> AgentState:
        hits = [
            VectorHit(
                chunk_id=item["chunk_id"],
                score=float(item["score"]),
                payload=item["payload"],
            )
            for item in state.get("hits", [])
        ]
        state["answer"] = self.llm.generate(state["question"], hits)
        state["trace_nodes"] = [*state.get("trace_nodes", []), "generate"]
        return state

    def _refuse(self, state: AgentState) -> AgentState:
        state["answer"] = "当前课程资料中没有检索到足够相关的内容，无法可靠回答这个问题。"
        state["trace_nodes"] = [*state.get("trace_nodes", []), "refuse"]
        return state


@lru_cache
def get_agent() -> CoursePilotAgent:
    return CoursePilotAgent()
