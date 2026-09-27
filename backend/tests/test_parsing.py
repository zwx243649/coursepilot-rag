from __future__ import annotations

from app.services.parsing import ExtractedPage, chunk_pages


def _page(text: str, page_number: int = 1) -> ExtractedPage:
    return ExtractedPage(page_number=page_number, text=text)


def test_repeated_page_headers_are_dropped():
    pages = [
        _page(
            "机器学习-引言 2026年03月\n\n"
            "第 %d 页正文，讲解机器学习的基本概念、发展历史与常见类型。" % index
            + "补充说明内容。" * 30,
            page_number=index,
        )
        for index in range(1, 6)
    ]
    chunks = chunk_pages(pages, 700, 100)
    assert chunks
    assert all("2026年03月" not in chunk.content for chunk in chunks)


def test_heading_is_carried_into_following_chunk():
    text = "甲" * 400 + "\n\n## 新章节\n\n" + "乙" * 400
    chunks = chunk_pages([_page(text)], 700, 100)
    assert len(chunks) >= 2
    assert any("## 新章节" in chunk.content for chunk in chunks)
    headed = [chunk for chunk in chunks if "## 新章节" in chunk.content]
    assert headed[0].section == "新章节"


def test_section_is_inherited_by_later_chunks():
    text = "## 概述\n\n" + "内容说明。" * 200
    chunks = chunk_pages([_page(text)], 700, 100)
    assert len(chunks) >= 2
    assert all(chunk.section == "概述" for chunk in chunks)


def test_chunks_keep_overlap_at_a_clean_boundary():
    text = "".join("第%d句话，内容需要更长一些。" % index + "补充说明。" * 6 for index in range(1, 60))
    chunks = chunk_pages([_page(text)], 400, 100)
    assert len(chunks) > 2
    for previous, current in zip(chunks, chunks[1:]):
        probe = current.content[:10]
        assert probe in previous.content, f"overlap missing between {probe!r}"


def test_noise_only_pages_produce_no_chunks():
    chunks = chunk_pages([_page("─── ╯ 12 。\n\n谢 谢！")], 700, 100)
    assert chunks == []
