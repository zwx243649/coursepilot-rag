from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Course, Document
from app.services.ingestion import ingest_document


logger = logging.getLogger(__name__)

SAMPLE_COURSE = """# AI 应用开发课程资料

## 检索增强生成

检索增强生成（RAG）先从外部知识库检索与问题相关的资料片段，再把这些片段放入大语言模型的上下文，让模型基于资料生成回答。RAG 的核心价值是补充模型训练数据之外的知识，并通过引用原文降低幻觉风险。

一个标准的 RAG 流程包括文档解析、文本切片、向量化、向量检索、上下文组装和答案生成。文档切片的长度与重叠范围会直接影响召回质量。切片过短容易丢失上下文，切片过长又会引入无关信息。

## Qdrant 与 PostgreSQL

Qdrant 是面向向量检索的数据库，适合保存文本切片对应的 embedding，并通过余弦相似度寻找语义接近的内容。PostgreSQL 适合保存用户、课程、文档元数据、会话记录和任务状态，它负责结构化数据与事务一致性。

RAG 系统通常会同时使用 Qdrant 和 PostgreSQL。Qdrant 返回命中的切片标识与相似度，PostgreSQL 再提供文档名称、权限、课程归属和会话信息。这种分工比把全部数据都塞进一个数据库更容易扩展。

## LangGraph Agent

LangGraph 用来把复杂任务组织成有状态的工作流。一个课程问答 Agent 可以包含问题分析、查询改写、资料检索、相关性判断、回答生成和引用校验等节点。

当检索分数低于阈值时，工作流可以进入拒绝节点，明确说明资料不足，而不是让模型自由编造。更高阶的实现还可以加入重试、混合检索、重排序、SQL 查询和联网搜索工具。

## 评测指标

检索评测通常关注 Hit Rate、MRR、关键词覆盖率、答案忠实度和端到端延迟。测试集应当包含可以直接从资料回答的问题、需要跨切片综合的问题，以及资料中确实没有答案的问题。

没有评测的 RAG 项目只能展示效果，无法说明系统是否稳定。保存固定测试集并记录每次改动前后的指标，是项目工程化的重要步骤。
"""


def seed_demo_data() -> None:
    settings = get_settings()
    if not settings.seed_demo:
        return

    session = SessionLocal()
    try:
        if (session.scalar(select(func.count(Course.id))) or 0) > 0:
            return

        course = Course(
            name="AI 应用开发",
            description="从 RAG 到 Agent 的课程资料示例",
            color="#0F766E",
        )
        session.add(course)
        session.flush()

        sample_path = settings.upload_dir / "coursepilot-sample.md"
        sample_path.write_text(SAMPLE_COURSE, encoding="utf-8")
        document = Document(
            course_id=course.id,
            original_name="RAG 与 Agent 课程讲义.md",
            stored_path=str(sample_path),
            mime_type="text/markdown",
            status="queued",
        )
        session.add(document)
        session.commit()
        ingest_document(document.id)
    except Exception:
        session.rollback()
        logger.exception("Could not seed the demo course")
    finally:
        session.close()

