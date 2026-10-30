"""Render the long-form pages, docs/writeup.md -> site/writeup.html and docs/methodology.md ->
site/methodology.html, in the map page's design (same fonts, color tokens and nav). Math
($...$, $$...$$) is typeset with KaTeX on pages that have it.

    uv run python scripts/build_writeup.py

docs/writeup.md is the source: it reads on GitHub too, and its images (img/...) resolve
both in docs/ and in site/ (build_mapbook.py --site copies docs/img into site/img).
"""

from __future__ import annotations

import html
import importlib.util
import re
from pathlib import Path

import mistune

ROOT = Path(__file__).resolve().parents[1]
PAGES = [("writeup", ROOT / "docs" / "writeup.md", "img/map-how-model-was-built.png"),
         ("methodology", ROOT / "docs" / "methodology.md", "img/map-how-model-was-built.png")]
KATEX = """<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.querySelector('.article'), {delimiters: [{left: '$$', right: '$$', display: true}, {left: '\\\\(', right: '\\\\)', display: false}]})"></script>"""


def nav(current: str) -> str:
    items = [("./", "Map", "map"), ("writeup.html", "Write-up", "writeup"), ("methodology.html", "Methodology", "methodology"),
             ("replay.html", "Election-night replay", "replay")]
    links = "\n".join(f'    <a href="{h}"{" aria-current=\"page\"" if k == current else ""}>{t}</a>' for h, t, k in items)
    return f"""<nav class="site-nav" aria-label="Site">
  <div class="site-nav-in">
{links}
    <a href="{BM.REPO_URL}">Code &amp; notebooks <span class="ext" aria-hidden="true">↗</span></a>
  </div>
</nav>"""

_spec = importlib.util.spec_from_file_location("build_mapbook", ROOT / "scripts" / "build_mapbook.py")
BM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BM)

ARTICLE_CSS = """
.article { max-width: 760px; margin: 0 auto; padding-block: 32px 64px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.article h1 { font: 700 40px/1.05 var(--display); text-transform: uppercase; letter-spacing: 0.005em; margin: 0 0 6px; text-wrap: balance; }
.article .byline { color: var(--ink-3); font-size: 14px; margin: 0 0 24px; }
.article h2 { font: 700 24px/1.1 var(--display); text-transform: uppercase; letter-spacing: 0.02em; margin: 40px 0 10px; }
.article p, .article li { font-size: 16.5px; line-height: 1.65; color: var(--ink); }
.article p { margin: 0 0 14px; }
.article ul { padding-left: 22px; margin: 0 0 16px; display: grid; gap: 4px; }
.article a { color: var(--dem); text-underline-offset: 2px; }
.article strong { font-weight: 650; }
.article hr { border: 0; border-top: 1px solid var(--rule); margin: 28px 0; }
.article img { display: block; max-width: 100%; height: auto; border: 1px solid var(--rule); border-radius: 8px; margin: 18px 0 6px; }
.article p:has(> img) { margin: 0; }
.article em { color: var(--ink-2); }
.article pre { background: var(--paper); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 14px; overflow-x: auto; font-size: 14px; }
.article code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.92em; }
.article .tbl-wrap { overflow-x: auto; margin: 10px 0 18px; }
.article table { width: 100%; border-collapse: collapse; font-size: 14.5px; font-variant-numeric: tabular-nums; background: var(--paper); border: 1px solid var(--rule); border-radius: 8px; }
.article th { text-align: left; font: 600 12px var(--body); color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.04em; padding: 9px 12px; border-bottom: 1px solid var(--rule); }
.article td { padding: 8px 12px; border-bottom: 1px solid var(--rule); }
.article tr:last-child td { border-bottom: 0; }
.article td:last-child, .article th:last-child { text-align: right; }
.article h3 { font: 700 17px/1.2 var(--display); text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-2); margin: 26px 0 8px; }
.article .math { overflow-x: auto; }
.article ol.refs { font-size: 14.5px; padding-left: 24px; display: grid; gap: 6px; }
.article ol.refs li { font-size: 14.5px; line-height: 1.5; color: var(--ink-2); }
.article sup a, .article a.cite { text-decoration: none; }
@media (max-width: 520px) { .article h1 { font-size: 30px; } .article p, .article li { font-size: 16px; } }
"""


def front_matter(text: str) -> tuple[dict, str]:
    meta = {}
    if text.startswith("---"):
        _, fm, text = text.split("---", 2)
        for line in fm.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta, text


def page_css() -> str:
    """The map page's fonts link and its whole <style> (tokens, both themes, base rules)."""
    tpl = (BM.WEB / "mapbook.html").read_text()
    fonts = re.search(r'<link rel="preconnect"[^>]*>\s*<link rel="stylesheet"[^>]*>', tpl).group(0)
    style = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)
    return fonts, style


def render(key: str, src: Path, og_img: str) -> Path:
    meta, body = front_matter(src.read_text())
    body = re.sub(r"^# .*\n", "", body.lstrip(), count=1)            # the title is rendered from front matter
    body = re.sub(r"^\*Axel Browne · [^*]*\*\n", "", body.lstrip(), count=1)  # so is the byline
    md = mistune.create_markdown(plugins=["table", "math", "url"], escape=False)
    content = md(body)
    content = re.sub(r"<table>", '<div class="tbl-wrap"><table>', content).replace("</table>", "</table></div>")
    has_math = 'class="math"' in content
    title, desc = meta.get("title", key.title()), meta.get("description", "")
    fonts, style = page_css()
    e = html.escape
    url = BM.SITE_URL + f"{key}.html"
    img = BM.SITE_URL + og_img
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<link rel="icon" href="{BM.FAVICON}">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{img}">
{fonts}
{KATEX if has_math else ""}
<style>{style}
{BM.SITE_CSS}
{ARTICLE_CSS}</style>
</head>
<body>
{nav(key)}
<article class="article">
<h1>{e(title)}</h1>
<p class="byline">Axel Browne · {e(meta.get("date", ""))} · <a href="{BM.REPO_URL}/blob/main/docs/{src.name}">source</a></p>
{content}
</article>
</body>
</html>
"""
    out = ROOT / "site" / f"{key}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"{out}  {len(page) / 1e3:.0f} KB")
    return out


def main() -> None:
    for key, src, img in PAGES:
        if src.exists():
            render(key, src, img)


if __name__ == "__main__":
    main()
