/**
 * Render docs/项目说明.md into a styled, print-ready HTML file.
 *
 * Useful when you want to share the doc as a PDF: open the generated HTML in
 * a browser and print to PDF, or run Edge/Chrome headless:
 *   msedge --headless=new --no-pdf-header-footer --print-to-pdf=out.pdf file:///...html
 *
 * Run with:  node scripts/build_doc_html.js
 * (needs the `marked` package available to Node)
 */

const fs = require('fs');
const path = require('path');
const { marked } = require('marked');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'docs', '项目说明.md');
const OUT_DIR = path.join(ROOT, 'share');
const OUT_HTML = path.join(OUT_DIR, 'coursepilot-doc.html');

const css = `
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
`;

fs.mkdirSync(OUT_DIR, { recursive: true });

const markdown = fs.readFileSync(SRC, 'utf8');
const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>CoursePilot 项目说明</title>
<style>${css}</style>
</head>
<body><article>${marked.parse(markdown)}</article></body>
</html>`;

fs.writeFileSync(OUT_HTML, html, 'utf8');
console.log('html written:', OUT_HTML, fs.statSync(OUT_HTML).size, 'bytes');
