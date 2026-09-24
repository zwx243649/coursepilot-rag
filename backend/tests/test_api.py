from __future__ import annotations

from io import BytesIO

from app.services.parsing import ExtractedPage, chunk_pages


SAMPLE_TEXT = """检索增强生成会先从课程知识库检索相关资料，再把资料放入大语言模型上下文。
Qdrant 用来保存向量并执行相似度检索，PostgreSQL 用来保存文档元数据和会话记录。
LangGraph 适合把检索、判断和生成组织成有状态的工作流。
"""


def create_course(client) -> str:
    response = client.post(
        "/api/courses",
        json={
            "name": "测试课程",
            "description": "API 测试",
            "color": "#0F766E",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_course_upload_chat_and_evaluation(client):
    course_id = create_course(client)

    upload = client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("notes.txt", BytesIO(SAMPLE_TEXT.encode("utf-8")), "text/plain")},
    )
    assert upload.status_code == 202
    document_id = upload.json()["id"]

    document = client.get(f"/api/documents/{document_id}")
    assert document.status_code == 200
    assert document.json()["status"] == "ready"
    assert document.json()["chunk_count"] >= 1

    chat = client.post(
        "/api/chat",
        json={
            "course_id": course_id,
            "question": "Qdrant 和 PostgreSQL 分别负责什么？",
        },
    )
    assert chat.status_code == 200
    payload = chat.json()
    assert payload["answer"]
    assert payload["citations"]
    assert payload["trace"]["decision"] == "generate"

    evaluation = client.post(
        "/api/evaluations/run",
        json={
            "course_id": course_id,
            "top_k": 3,
            "cases": [
                {
                    "question": "LangGraph 的作用是什么？",
                    "expected_terms": ["LangGraph", "工作流"],
                }
            ],
        },
    )
    assert evaluation.status_code == 200
    result = evaluation.json()
    assert result["hit_rate"] == 1.0
    assert result["cases"][0]["hit"] is True


def test_health_and_course_list(client):
    course_id = create_course(client)
    health = client.get("/api/system/health")
    assert health.status_code == 200
    assert health.json()["database"] is True

    courses = client.get("/api/courses")
    assert courses.status_code == 200
    assert any(course["id"] == course_id for course in courses.json())


def test_chunking_does_not_create_overlap_tail():
    text = "测试段落。" * 260
    chunks = chunk_pages([ExtractedPage(page_number=1, text=text)], chunk_size=700, overlap=100)
    assert len(chunks) < 10
    assert all(len(chunk.content) <= 700 for chunk in chunks)
