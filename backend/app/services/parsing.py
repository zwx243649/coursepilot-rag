from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    text: str


@dataclass(slots=True)
class ChunkRecord:
    chunk_index: int
    page_number: int | None
    section: str | None
    content: str


def extract_pages(path: Path, mime_type: str) -> list[ExtractedPage]:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or mime_type == "application/pdf":
        reader = PdfReader(str(path))
        pages = [
            ExtractedPage(page_number=index + 1, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages)
        ]
        return pages

    raw = path.read_bytes()
    text = ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return [ExtractedPage(page_number=1, text=text)]


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_text(text: str, chunk_size: int, overlap: int, page_number: int) -> list[ChunkRecord]:
    text = _normalize_text(text)
    if not text:
        return []

    chunks: list[ChunkRecord] = []
    start = 0
    chunk_index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            window = text[start:end]
            candidates = [
                window.rfind("\n\n"),
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
                window.rfind(". "),
            ]
            boundary = max(candidates)
            if boundary >= int(chunk_size * 0.55):
                end = start + boundary + 1

        content = text[start:end].strip()
        if content:
            section_match = re.search(r"^#{1,6}\s+(.+)$", content, flags=re.MULTILINE)
            section = section_match.group(1).strip()[:255] if section_match else None
            chunks.append(
                ChunkRecord(
                    chunk_index=chunk_index,
                    page_number=page_number,
                    section=section,
                    content=content,
                )
            )
            chunk_index += 1

        if end >= len(text):
            break

        previous_start = start
        start = max(end - overlap, previous_start + 1)
    return chunks


def chunk_pages(
    pages: list[ExtractedPage],
    chunk_size: int,
    overlap: int,
) -> list[ChunkRecord]:
    if chunk_size <= 100:
        raise ValueError("CHUNK_SIZE must be greater than 100")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("CHUNK_OVERLAP must be between 0 and CHUNK_SIZE")

    records: list[ChunkRecord] = []
    for page in pages:
        for record in _split_text(page.text, chunk_size, overlap, page.page_number):
            record.chunk_index = len(records)
            records.append(record)
    return records
