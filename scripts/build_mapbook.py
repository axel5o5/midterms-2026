"""Build the map page (build/mapbook.html): every race and source from the latest
snapshot plus live market prices now, map shapes, and the 2025 swing layer.

    uv run python scripts/build_mapbook.py          # -> build/mapbook.html
    uv run python scripts/build_mapbook.py --site   # -> site/index.html (GitHub Pages) + site/img/

--site is the same page and data with a full HTML document around it, a top nav, social and
search metadata, and docs/img/*.png copied to site/img/. site/ is committed pre-built and
deployed as-is by .github/workflows/pages.yml.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

from midterms import geo as G
from midterms import house as H
from midterms import racebook as RB
from midterms.snapshot import ROOT

WEB = ROOT / "src" / "midterms" / "web"
OUT = ROOT / "build" / "mapbook.html"
SITE = ROOT / "site"
SITE_URL = "https://axel5o5.github.io/midterms-2026/"
REPO_URL = "https://github.com/axel5o5/midterms-2026"
SWING_STATES = {"VA": ("51", "Virginia"), "NJ": ("34", "New Jersey")}


def swing2025():
    try:
        from midterms import results2025 as R25
        d = R25.county_swing()
    except Exception as e:  # layer is optional until the 2025 data is in
        print(f"2025 layer skipped: {e!r}")
        return None, {}
    d["fips"] = d["fips"].astype(str).str.zfill(5)
    counties = G.counties(tuple(f for f, _ in SWING_STATES.values()))
    states = []
    for st, (fips, name) in SWING_STATES.items():
        s = d[d["state"] == st]
        if s.empty:
            continue
        tot = s["total"].sum()
        m25 = 100 * (s["dem"].sum() - s["rep"].sum()) / tot
        from midterms.live.baselines import county_baseline
        b24 = county_baseline(st)                                 # Harris's actual statewide 2024 margin
        m24 = float(100 * (b24["pres2024_dem"].sum() - b24["pres2024_gop"].sum()) / b24["pres2024_total"].sum())
        states.append(dict(st=st, fips=fips, name=name, margin25=round(m25, 2), margin24=round(m24, 2),
                           swing=round(m25 - m24, 2),
                           bbox=G.bbox({k: v for k, v in counties.items() if k.startswith(fips)})))
    rows = {r.fips: dict(county=r.county, margin25=round(r.margin25, 2), margin24=round(r.margin24, 2),
                         swing=round(r.swing, 2), total=float(r.total)) for r in d.itertuples()}
    return dict(states=states, counties=rows), counties


def method():
    """The model-selection backtest, for the page's 'how the model was built' section (notebook 04)."""
    import numpy as np
    from midterms import carryover as CO
    s, _ = CO.backtest(window=12)
    t = CO.table(12).dropna(subset=["fade", "pres", "hist"])
    t = t[(t["n_hist"] >= 2) & t["midterm"]]
    years = []
    for c in sorted(t["cycle"].unique()):
        tr, te = t[t["cycle"] != c], t[t["cycle"] == c]
        bp = float((tr["pres"] * tr["y"]).sum() / (tr["pres"] ** 2).sum())
        bf = float((tr["fade"] * tr["y"]).sum() / (tr["fade"] ** 2).sum())
        r = lambda e: float(np.sqrt(np.mean(e ** 2)))
        years.append(dict(year=int(c), none=r(te["y"]), carry=r(te["y"] - bp * te["pres"]), fade=r(te["y"] - bf * te["fade"])))
    b = CO.bootstrap(["pres"], 12)
    return dict(races=len(t), cycles=int(t["cycle"].nunique()), weight=CO.BETA_PRES,
                lo=float(b.loc["pres", "5%"]), hi=float(b.loc["pres", "95%"]),
                scores=[dict(spec=r.spec, rmse=round(r.rmse, 3)) for r in s.itertuples()], years=years)


SITE_CSS = """
body { margin: 0; }
/* the template's .wrap grid has an auto track, so the wide disagreement table pushed every section past
   the viewport at phone width; pin the track so .tbl-wrap scrolls inside its card instead */
.wrap { grid-template-columns: minmax(0, 1fr); }
.site-nav { background: var(--paper); border-bottom: 1px solid var(--rule); }
.site-nav-in { max-width: 1240px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); display: flex; flex-wrap: wrap; gap: 0 22px; }
.site-nav a { font: 600 14px/1 var(--display); text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-2); text-decoration: none; padding: 13px 0 11px; border-bottom: 2px solid transparent; }
.site-nav a:hover { color: var(--ink); }
.site-nav a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--ink); }
.site-nav a:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.site-nav .ext { color: var(--ink-3); font-weight: 500; }
header .asof { font-size: 14px; color: var(--ink-2); margin-top: 10px; }
header .asof b { color: var(--ink); font-weight: 600; }
footer a { color: inherit; }
@media (max-width: 520px) { .site-nav-in { gap: 0 16px; } .site-nav a { font-size: 13px; padding: 10px 0 8px; } }
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='6' fill='%2315171a'/%3E"
           "%3Crect x='6' y='6' width='9' height='20' rx='1.5' fill='%232457a6'/%3E"
           "%3Crect x='17' y='6' width='9' height='20' rx='1.5' fill='%23b0322b'/%3E%3C/svg%3E")


def _swap(page: str, old: str, new: str) -> str:
    assert page.count(old) == 1, f"site build: expected one {old[:60]!r} in the template"
    return page.replace(old, new)


def site_page(page: str, asof: str) -> str:
    """The artifact page as a standalone public document: doctype, viewport, metadata, nav."""
    when = dt.datetime.fromisoformat(asof)
    day = f"{when:%b} {when.day}, {when.year}"
    title = "2026 Midterms Map: every race, every source"
    desc = (f"Every 2026 Senate, House and governor race with each source side by side: a poll-based model, "
            f"Split Ticket, the polls, the raters, Kalshi and Polymarket. Data as of {day}.")
    img = SITE_URL + "img/map-senate-iowa.png"
    e = lambda x: html.escape(x, quote=True)
    head = f"""<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE_URL}">
<link rel="icon" href="{FAVICON}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="2026 Midterms Map">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{SITE_URL}">
<meta property="og:image" content="{img}">
<meta property="og:image:alt" content="The 2026 Senate map with the Iowa race open: each source's chance for the Democrat side by side">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{img}">"""
    nav = f"""<nav class="site-nav" aria-label="Site">
  <div class="site-nav-in">
    <a href="./" aria-current="page">Map</a>
    <a href="writeup.html">Write-up</a>
    <a href="methodology.html">Methodology</a>
    <a href="replay.html">Election-night replay</a>
    <a href="{REPO_URL}">Code &amp; notebooks <span class="ext" aria-hidden="true">↗</span></a>
  </div>
</nav>
<div class="wrap">"""
    page = "<!doctype html>\n<html lang=\"en\">\n" + page
    page = _swap(page, '<title>2026 Midterms Map</title>', f"<title>{e(title)}</title>")
    page = _swap(page, '<meta name="claude:viewport-fit-sides" content="cover">', head)
    page = _swap(page, "</style>", SITE_CSS + "</style>")
    # Polymarket is the only market on the public site
    for a, b in (("the raters, Kalshi and Polymarket.", "the raters and Polymarket."),
                 ("from the average of Kalshi and Polymarket, biggest first.", "from Polymarket's price, biggest first."),
                 ("Kalshi and Polymarket mid prices", "Polymarket mid prices")):
        assert a in page, f"site build: template text changed: {a!r}"
        page = page.replace(a, b)
    assert "Kalshi" not in re.sub(r"<script.*?</script>", "", page, flags=re.S), "site build: Kalshi text left on the public page"
    page = _swap(page, '<div class="wrap">', nav)
    page = _swap(page, '<div class="asof">Market prices and forecasts as of <span id="asof"></span></div>',
                 f'<div class="asof">Data as of <b id="asof">{e(day)}</b>. Market prices, polls and forecasts were '
                 f'captured then; this page is a snapshot and does not update.</div>')
    page = _swap(page, "  </footer>",
                 f'    <div>Code, notebooks and derived data: <a href="{REPO_URL}">github.com/axel5o5/midterms-2026</a> (MIT). '
                 "Not affiliated with any of the sources above.</div>\n  </footer>")
    # the shared JS writes a short local time into #asof; on the public page add the year and time zone
    page = _swap(page, "MapBook.app(BOOK);</script>",
                 "MapBook.app(BOOK);\n{ const a = document.getElementById('asof'); "
                 "if (a) a.textContent = new Date(BOOK.asof).toLocaleString([], { year: 'numeric', month: 'short', "
                 "day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }); }</script>")
    return page


def copy_images() -> int:
    src = sorted((ROOT / "docs" / "img").glob("*.png"))
    if not src:
        return 0
    (SITE / "img").mkdir(parents=True, exist_ok=True)
    for f in src:
        shutil.copyfile(f, SITE / "img" / f.name)
    # og:image is img/map-senate-iowa.png; if the screenshots come in light/dark pairs, use the light one
    og, light = SITE / "img" / "map-senate-iowa.png", SITE / "img" / "map-senate-iowa-light.png"
    if not (ROOT / "docs" / "img" / og.name).exists() and light.exists():
        shutil.copyfile(light, og)
    return len(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", action="store_true", help="write the public GitHub Pages build to site/ instead")
    args = ap.parse_args()
    # the public site never carries Kalshi data (developer agreement v1.1, section 3)
    book = RB.build(venues=("polymarket",) if args.site else ("kalshi", "polymarket"))
    book["method"] = method()
    sw, counties = swing2025()
    book["swing2025"] = sw
    book["geo"] = dict(states=G.states(), counties=counties)
    book["tiles"] = G.house_tiles(H.districts()["district"].tolist())
    page = (WEB / "mapbook.html").read_text()
    page = page.replace("/*MAPBOOK_JS*/", (WEB / "mapbook.js").read_text())
    page = page.replace("/*BOOK*/", json.dumps(book, separators=(",", ":")).replace("</", "<\\/"))
    out = OUT
    if args.site:
        page, out = site_page(page, book["asof"]), SITE / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"{out}  {len(page) / 1e6:.2f} MB  races={len(book['races'])}  2025={'yes' if sw else 'no'}")
    if args.site:
        n = copy_images()
        print(f"site/img: {n} screenshot(s) copied from docs/img" if n else "site/img: no docs/img/*.png yet, nothing copied")
        if not (SITE / "img" / "map-senate-iowa.png").exists():
            print("note: site/img/map-senate-iowa.png is missing; og:image and twitter:image point at it")


if __name__ == "__main__":
    main()
