from __future__ import annotations

import math
import re
from functools import lru_cache

import httpx

from app.config import get_settings
from app.services.embeddings import _hash_tokens
from app.services.http_client import post_json
from app.services.vector_store import VectorHit


_SENTENCE_RE = re.compile(r"(?<=[。！？.!?])\s*|\n+")

_CHAT_TIMEOUT_SECONDS = 60.0
_CHAT_MAX_RETRIES = 2
_REWRITE_TIMEOUT_SECONDS = 30.0

_REWRITE_PROMPT = (
    "You rewrite a user question into a single retrieval query. Keep the original "
    "intent, add useful synonyms, and when the source material is likely English "
    "also include the key English terms. Output only the query text: no "
    "explanation, no bullet points, no quotes."
)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _sentence_score(question: str, sentence: str) -> float:
    query_tokens = {token for token, _ in _hash_tokens(question)}
    if not query_tokens:
        return 0.0
    sentence_tokens = {token for token, _ in _hash_tokens(sentence)}
    return len(query_tokens & sentence_tokens) / math.sqrt(max(1, len(query_tokens)))


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def provider(self) -> str:
        if self.settings.llm_provider == "openai" and self.settings.llm_api_key:
            return "openai"
        return "demo"

    def generate(self, question: str, hits: list[VectorHit]) -> str:
        if not hits:
            return "当前课程资料中没有检索到足够相关的内容，无法可靠回答这个问题。"
        if self.provider == "openai":
            return self._openai_chat(question, hits)
        return self._demo_answer(question, hits)

    def _demo_answer(self, question: str, hits: list[VectorHit]) -> str:
        ranked_sentences: list[tuple[float, int, str]] = []
        for citation_index, hit in enumerate(hits[:4], start=1):
            content = str(hit.payload.get("content", ""))
            for sentence in _SENTENCE_RE.split(content):
                cleaned = " ".join(sentence.split()).strip()
                if len(cleaned) < 12:
                    continue
                ranked_sentences.append(
                    (_sentence_score(question, cleaned), citation_index, cleaned)
                )

        ranked_sentences.sort(key=lambda item: item[0], reverse=True)
        selected: list[tuple[int, str]] = []
        seen: set[str] = set()
        for score, citation_index, sentence in ranked_sentences:
            key = sentence[:80]
            if key in seen:
                continue
            selected.append((citation_index, sentence[:320]))
            seen.add(key)
            if len(selected) >= 4:
                break

        if not selected:
            selected = [
                (index, str(hit.payload.get("content", ""))[:320])
                for index, hit in enumerate(hits[:3], start=1)
            ]

        if _contains_cjk(question):
            lines = ["根据当前课程资料，可以归纳为："]
            lines.extend(
                f"- {sentence} [{citation_index}]"
                for citation_index, sentence in selected
            )
            lines.append("\n以上内容仅基于当前检索到的资料片段。")
            return "\n".join(lines)

        lines = ["Based on the indexed course materials:"]
        lines.extend(
            f"- {sentence} [{citation_index}]"
            for citation_index, sentence in selected
        )
        lines.append("\nThis answer is limited to the retrieved source excerpts.")
        return "\n".join(lines)

    def _openai_chat(self, question: str, hits: list[VectorHit]) -> str:
        context_blocks = []
        for index, hit in enumerate(hits[:6], start=1):
            payload = hit.payload
            context_blocks.append(
                "\n".join(
                    [
                        f"[{index}] {payload.get('document_name', '资料')}",
                        f"页码: {payload.get('page_number') or '未知'}",
                        str(payload.get("content", "")),
                    ]
                )
            )

        system_prompt = (
            "You are CoursePilot, a course-material question answering assistant. "
            "Answer only from the supplied context. Cite claims with [1], [2] style "
            "references. If the context is insufficient, say so explicitly. "
            "Reply in the same language as the user's question."
        )
        context_text = "\n\n".join(context_blocks)
        user_prompt = f"Question:\n{question}\n\nContext:\n\n{context_text}"
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        try:
            response = post_json(
                f"{self.settings.llm_base_url}/chat/completions",
                headers=headers,
                payload=payload,
                timeout=_CHAT_TIMEOUT_SECONDS,
                retries=_CHAT_MAX_RETRIES,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Chat completion request failed: {exc}") from exc
        return response.json()["choices"][0]["message"]["content"].strip()

    def rewrite_query(self, question: str) -> str | None:
        """Rewrite a question into a retrieval query; None means "keep the original".

        Best-effort by design: an offline provider or a failed call must never
        break retrieval, so callers fall back to the raw question.
        """
        if self.provider != "openai":
            return None
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _REWRITE_PROMPT},
                {"role": "user", "content": question},
            ],
        }
        try:
            response = post_json(
                f"{self.settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                payload=payload,
                timeout=_REWRITE_TIMEOUT_SECONDS,
                retries=_CHAT_MAX_RETRIES,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None
        text = text.strip().strip('"').strip()
        return text[:400] or None

    def health(self) -> dict[str, str | bool]:
        configured = self.provider == "openai"
        return {
            "provider": self.provider,
            "model": self.settings.llm_model if configured else "local-extractive",
            "configured": configured or self.provider == "demo",
        }


@lru_cache
def get_llm() -> LLMService:
    return LLMService()
