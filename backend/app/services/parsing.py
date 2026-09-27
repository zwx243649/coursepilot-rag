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


_HEADING_PATTERN = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
_DECORATION_RE = re.compile(r"^[\s\W_]*$", re.UNICODE)
_SENTENCE_ENDINGS = "。！？!?；;"


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_noise_block(block: str) -> bool:
    """Drop blocks that carry no retrievable meaning (page numbers, rules, tags)."""
    text = " ".join(block.split())
    if len(text) < 12:
        return True
    if not re.search(r"[A-Za-z\u3400-\u9fff]", text):
        return True
    if _DECORATION_RE.match(text):
        return True
    return False


def _boilerplate_lines(pages: list[ExtractedPage]) -> set[str]:
    """Lines repeated on most pages are headers/footers/navigation, not content."""
    if len(pages) < 3:
        return set()
    counts: dict[str, int] = {}
    for page in pages:
        seen = {
            line.strip()
            for line in _normalize_text(page.text).split("\n")
            if len(line.strip()) >= 6
        }
        for line in seen:
            counts[line] = counts.get(line, 0) + 1
    threshold = max(3, int(len(pages) * 0.4))
    return {line for line, count in counts.items() if count >= threshold}


def _clean_text(text: str, drop_lines: set[str]) -> str:
    text = _normalize_text(text)
    if not text:
        return ""
    paragraphs: list[str] = []
    pending_heading: str | None = None
    for raw in re.split(r"\n{2,}", text):
        kept = [
            line.strip()
            for line in raw.split("\n")
            if line.strip() and line.strip() not in drop_lines
        ]
        if not kept:
            continue
        block = "\n".join(kept)
        if _HEADING_PATTERN.fullmatch(block):
            # A heading on its own is not worth retrieving, but it belongs with
            # the section it introduces, so carry it into the next block.
            pending_heading = block if pending_heading is None else f"{pending_heading}\n\n{block}"
            continue
        if pending_heading is not None:
            block = f"{pending_heading}\n\n{block}"
            pending_heading = None
        if _is_noise_block(block):
            continue
        paragraphs.append(block)
    if pending_heading is not None and paragraphs:
        paragraphs[-1] = f"{paragraphs[-1]}\n\n{pending_heading}"
    return "\n\n".join(paragraphs)


def _cut_point(window: str, chunk_size: int) -> tuple[int, int]:
    """Find where to cut inside a window, preferring structural boundaries.

    Returns (offset, extra) so the cut lands at ``offset + extra``: paragraph and
    heading cuts consume the blank line, sentence cuts keep the punctuation.
    """
    minimum = int(chunk_size * 0.5)

    heading_at = None
    for match in re.finditer(r"\n(?=#{1,6}\s)", window):
        if match.start() >= minimum:
            heading_at = match.start()
    if heading_at is not None:
        return heading_at, 1

    paragraph_at = window.rfind("\n\n")
    if paragraph_at >= minimum:
        return paragraph_at, 2

    sentence_candidates = [window.rfind(char) for char in _SENTENCE_ENDINGS]
    sentence_candidates.extend([window.rfind(". "), window.rfind(".\n")])
    sentence_at = max(sentence_candidates)
    if sentence_at >= minimum:
        if window[sentence_at : sentence_at + 2] in {". ", ".\n"}:
            return sentence_at + 1, 1
        return sentence_at + 1, 0

    space_at = max(window.rfind(" "), window.rfind("\n"))
    if space_at >= minimum:
        return space_at, 1

    return chunk_size, 0


def _snap_forward(text: str, position: int, limit: int) -> int:
    """Move an overlap start forward to the next clean sentence or line start."""
    for index in range(position, min(limit, len(text))):
        char = text[index]
        if char == "\n" or char in _SENTENCE_ENDINGS:
            return index + 1
        if char == "." and index + 1 < len(text) and text[index + 1] in " \n":
            return index + 2
    return position


def _section_for(text: str, content: str, start: int) -> str | None:
    inside = _HEADING_PATTERN.search(content)
    if inside:
        return inside.group(1).strip()[:255]
    heading = None
    for match in _HEADING_PATTERN.finditer(text[:start]):
        heading = match.group(1).strip()[:255]
    return heading


def _split_text(
    text: str,
    chunk_size: int,
    overlap: int,
    page_number: int,
    drop_lines: set[str] | None = None,
) -> list[ChunkRecord]:
    text = _clean_text(text, drop_lines or set())
    if not text:
        return []

    chunks: list[ChunkRecord] = []
    start = 0
    chunk_index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            offset, extra = _cut_point(text[start:end], chunk_size)
            end = start + offset + extra

        content = text[start:end].strip()
        if content:
            chunks.append(
                ChunkRecord(
                    chunk_index=chunk_index,
                    page_number=page_number,
                    section=_section_for(text, content, start),
                    content=content,
                )
            )
            chunk_index += 1

        if end >= len(text):
            break

        previous_start = start
        next_start = max(end - overlap, previous_start + 1)
        start = _snap_forward(text, next_start, end)
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

    drop_lines = _boilerplate_lines(pages)
    records: list[ChunkRecord] = []
    for page in pages:
        for record in _split_text(
            page.text,
            chunk_size,
            overlap,
            page.page_number,
            drop_lines,
        ):
            record.chunk_index = len(records)
            records.append(record)
    return records
