from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Course, Document, DocumentSource, ImportJob, utc_now
from app.services.ingestion import ingest_document


USER_AGENT = "CoursePilotDocsImporter/0.1"
ASSET_SUFFIXES = {
    ".7z",
    ".css",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".pdf",
    ".png",
    ".svg",
    ".tar",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}


def _normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _github_raw_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.netloc.lower() != "github.com":
        return url
    fragments = [part for part in parts.path.split("/") if part]
    if len(fragments) >= 5 and fragments[2] == "blob":
        return urlunsplit(
            (
                "https",
                "raw.githubusercontent.com",
                "/" + "/".join([fragments[0], fragments[1], *fragments[3:]]),
                parts.query,
                "",
            )
        )
    return url


def _same_scope(candidate: str, root: str, same_path_only: bool) -> bool:
    candidate_parts = urlsplit(candidate)
    root_parts = urlsplit(root)
    if candidate_parts.scheme not in {"http", "https"}:
        return False
    if candidate_parts.netloc.lower() != root_parts.netloc.lower():
        return False
    if not same_path_only:
        return True

    root_path = root_parts.path or "/"
    if not root_path.endswith("/"):
        root_path = root_path.rsplit("/", 1)[0] + "/"
    return candidate_parts.path.startswith(root_path)


def _looks_like_document_link(url: str) -> bool:
    parts = urlsplit(url)
    suffix = Path(parts.path).suffix.lower()
    if suffix in ASSET_SUFFIXES:
        return False
    if any(token in parts.path.lower() for token in ("/login", "/signin", "/search")):
        return False
    return True


def _clean_text(text: str) -> str:
    lines = [" ".join(line.split()).strip() for line in text.splitlines()]
    compact: list[str] = []
    for line in lines:
        if not line:
            if compact and compact[-1] != "":
                compact.append("")
            continue
        compact.append(line)
    return "\n".join(compact).strip()


def _extract_html(html: str, url: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(
        ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]
    ):
        element.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    heading = soup.find("h1")
    if heading:
        title = heading.get_text(" ", strip=True) or title

    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = _clean_text(root.get_text("\n", strip=True))

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        candidate = _normalize_url(urljoin(url, anchor["href"]))
        if _looks_like_document_link(candidate):
            links.append(candidate)
    return title or urlsplit(url).path.strip("/").split("/")[-1] or "官方文档", text, links


def _extract_plain_text(content: str, url: str) -> tuple[str, str, list[str]]:
    first_heading = next(
        (
            line.lstrip("#").strip()
            for line in content.splitlines()
            if line.strip().startswith("#")
        ),
        "",
    )
    fallback = urlsplit(url).path.rsplit("/", 1)[-1] or "官方文档"
    return first_heading or fallback, _clean_text(content), []


def _fetch_page(client: httpx.Client, url: str) -> tuple[str, str, list[str]]:
    response = client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    content = response.text
    if "html" in content_type or "<html" in content[:500].lower():
        return _extract_html(content, str(response.url))
    return _extract_plain_text(content, str(response.url))


def _safe_filename(title: str, url: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", title).strip("-")[:60]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug or 'docs'}-{digest}.md"


def run_web_import(job_id: str) -> None:
    settings = get_settings()
    session = SessionLocal()
    job = session.get(ImportJob, job_id)
    if job is None:
        session.close()
        return

    try:
        course = session.get(Course, job.course_id)
        if course is None:
            raise RuntimeError("Course not found")

        job.status = "processing"
        job.updated_at = utc_now()
        session.commit()

        root_url = _github_raw_url(_normalize_url(job.root_url))
        queue = [root_url]
        queued = {root_url}
        visited: set[str] = set()
        imported = 0

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain,text/markdown;q=0.9,*/*;q=0.5",
        }
        with httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            while queue and len(visited) < job.max_pages:
                current_url = queue.pop(0)
                if current_url in visited:
                    continue
                visited.add(current_url)

                title, text, links = _fetch_page(client, current_url)
                if len(text) >= 80:
                    existing_source = session.scalar(
                        select(DocumentSource).where(
                            DocumentSource.course_id == job.course_id,
                            DocumentSource.url == current_url,
                        )
                    )
                    if existing_source is None:
                        content = (
                            f"# {title}\n\n"
                            f"> 来源：{current_url}\n\n"
                            f"{text}\n"
                        )
                        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                        stored_path = settings.upload_dir / _safe_filename(title, current_url)
                        stored_path.write_text(content, encoding="utf-8")

                        document = Document(
                            course_id=job.course_id,
                            original_name=f"{title}.md",
                            stored_path=str(stored_path),
                            mime_type="text/markdown",
                            status="queued",
                        )
                        session.add(document)
                        session.flush()
                        session.add(
                            DocumentSource(
                                course_id=job.course_id,
                                document_id=document.id,
                                url=current_url,
                                title=title,
                                content_hash=content_hash,
                            )
                        )
                        session.commit()
                        ingest_document(document.id)
                        imported += 1
                        job.imported_count = imported
                        job.updated_at = utc_now()
                        session.commit()

                if len(visited) < job.max_pages:
                    for link in links:
                        if (
                            link not in queued
                            and _same_scope(link, root_url, job.same_path_only)
                            and len(queued) < job.max_pages * 4
                        ):
                            queue.append(link)
                            queued.add(link)

                job.discovered_count = len(visited)
                job.updated_at = utc_now()
                session.commit()
                time.sleep(0.15)

        job.status = "ready"
        job.discovered_count = len(visited)
        job.imported_count = imported
        job.error_message = None
        job.updated_at = utc_now()
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(ImportJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)[:1000]
            job.updated_at = utc_now()
            session.commit()
    finally:
        session.close()

