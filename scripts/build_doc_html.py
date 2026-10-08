"""Render a Markdown document into a styled, print-ready HTML file.

Usage:
    python scripts/build_doc_html.py docs/技术详解.md share/tech-detail.html

Then print it to PDF with Edge (no Node needed):
    msedge --headless=new --no-pdf-header-footer \\
           --print-to-pdf="share/技术详解.pdf" "file:///.../share/tech-detail.html"

The JavaScript version (scripts/build_doc_html.js) produces the same output when
Node is available; this one only needs the project virtualenv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import markdown


ROOT = Path(__file__).resolve().parents[1]

CSS = """
  :root { color-scheme: light; }
  body { margin: 0; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; line-height: 1.75; color: #1f2937; }
  article { max-width: 880px; margin: 0 auto; padding: 36px 44px 48px; }
  h1 { font-size: 27px; margin: 0 0 6px; padding-bottom: 10px; border-bottom: 2px solid #0f766e; }
  h2 { font-size: 20px; margin-top: 30px; color: #0f766e; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }
  h3 { font-size: 16px; margin-top: 22px; color: #111827; }
  p, li { font-size: 14px; }
  table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 13px; }
  th, td { border: 1px solid #d1d5db; padding: 7px 9px; text-align: left; vertical-align: top; }
  th { background: #f3f4f6; font-weight: 600; }
  tr:nth-child(even) td { background: #fafafa; }
  code { background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-family: Consolas, "Courier New", monospace; font-size: 12.5px; }
  pre { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 11px 13px; overflow-x: auto; }
  pre code { background: none; padding: 0; font-size: 12.5px; line-height: 1.6; }
  blockquote { margin: 14px 0; padding: 4px 14px; border-left: 3px solid #0f766e; color: #374151; }
  ul, ol { padding-left: 24px; }
  a { color: #0f766e; }
  hr { border: none; border-top: 1px solid #e5e7eb; margin: 28px 0; }
  @media print {
    article { padding: 0; max-width: none; }
    h2, h3 { page-break-after: avoid; }
    table, pre, blockquote { page-break-inside: avoid; }
  }
"""


def render(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8")
    title = source.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body><article>{body}</article></body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    print(f"html written: {destination} ({destination.stat().st_size} bytes)")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    source = Path(sys.argv[1])
    if not source.is_absolute():
        source = ROOT / source
    destination = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "share" / (source.stem + ".html")
    if not destination.is_absolute():
        destination = ROOT / destination
    render(source, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
