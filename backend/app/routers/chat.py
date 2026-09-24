from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Conversation, Course, Message
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatTrace,
    Citation,
    ConversationMessage,
)
from app.services.agent import get_agent


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    course = db.get(Course, payload.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    conversation = (
        db.get(Conversation, payload.conversation_id)
        if payload.conversation_id
        else None
    )
    if conversation is not None and conversation.course_id != payload.course_id:
        raise HTTPException(status_code=400, detail="Conversation belongs to another course")
    if conversation is None:
        conversation = Conversation(
            course_id=payload.course_id,
            title=payload.question.strip()[:80] or "新对话",
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.question.strip(),
    )
    db.add(user_message)
    db.commit()

    started = time.perf_counter()
    state = get_agent().run(payload.course_id, payload.question.strip())
    latency_ms = int((time.perf_counter() - started) * 1000)

    hits = state.get("hits", [])
    citations = [
        Citation(
            index=index,
            chunk_id=item["chunk_id"],
            document_id=str(item["payload"].get("document_id", "")),
            document_name=str(item["payload"].get("document_name", "资料")),
            page_number=item["payload"].get("page_number"),
            score=round(float(item["score"]), 4),
            excerpt=str(item["payload"].get("content", ""))[:360],
        )
        for index, item in enumerate(hits[:6], start=1)
    ]
    trace = ChatTrace(
        nodes=state.get("trace_nodes", []),
        decision=state.get("decision", "refuse"),
        retrieval_count=len(hits),
        latency_ms=latency_ms,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=state["answer"],
        citations=[citation.model_dump() for citation in citations],
        trace=trace.model_dump(),
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    return ChatResponse(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        answer=assistant_message.content,
        citations=citations,
        trace=trace,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ConversationMessage],
)
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> list[Message]:
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    )

