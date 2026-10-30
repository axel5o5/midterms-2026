"""Results you send from your own browser, for hosts the tool can't fetch itself.

Kansas: the Secretary of State's results site (ent.sos.ks.gov) sits behind a Cloudflare
bot challenge, so the tool never requests it. You open the page yourself (its
congressional page, national.html, which reloads itself every 5 seconds) and click the
"Send to dashboard" bookmark; the bookmark posts the page your browser already has to
the local dashboard (POST /ingest/ks). Nothing extra is requested from the state's
server. If the browser blocks the post, the bookmark copies the page instead and you
paste it into the dashboard's box. Chrome asks once per site before a page may reach
a local address ("local network access", checked on Chrome 156): allow it the first time.

The page carries every county's numbers for every race in its county-map hover boxes:
each race is a <div class='race'> with an <h3> title and a <map> whose <area> titles
hold "<County> County", "N of M precincts reporting" and rows like "D-Adam Hamilton |
40,227". Parsed into the same tidy frame as feeds.py, so the engine treats it like any
other feed.
"""

from __future__ import annotations

import datetime as dt
import html as htmlmod
import re
import threading
import time

import pandas as pd

from . import feeds as F

KS_RACES = {"SEN-KS": r"^United States Senate$"}   # race key -> h3 title pattern (general election)
_lock = threading.Lock()
_latest: dict[str, dict] = {}                        # state -> {"frame", "received", "page_time", "counties"}


def parse_ks(page: str, races: dict[str, str] = KS_RACES, non_r: dict[str, str] | None = None) -> pd.DataFrame:
    """Kansas results page HTML -> tidy rows (one per county x candidate, vote_type 'total')."""
    fl = F._fips_lookup("KS")
    rows = []
    ts = dt.datetime.now(dt.UTC)
    for block in re.split(r"<div class='race'>", page)[1:]:
        h3 = re.search(r"<h3>(.*?)</h3>", block, re.S)
        if not h3:
            continue
        title = htmlmod.unescape(re.sub(r"<[^>]+>", "", h3.group(1))).strip()
        key = next((k for k, pat in races.items() if re.search(pat, title)), None)
        if not key:
            continue
        for area in re.finditer(r"<area[^>]*?alt='([^']+)'[^>]*?title=\"(.*?)\"", block, re.S):
            county, tip = area.group(1), htmlmod.unescape(area.group(2))
            pr = re.search(r"(\d+)\s+of\s+(\d+)\s+precincts", tip)
            done = bool(pr) and pr.group(1) == pr.group(2) and pr.group(2) != "0"
            for party, name, votes in re.findall(r"<td[^>]*>\s*([A-Z]{1,3})-([^<]+?)\s*</td>\s*<td[^>]*>\s*([\d,]+)\s*</td>", tip):
                p = F._party(party)
                if non_r and name.strip() in non_r:
                    p = non_r[name.strip()]
                rows.append(dict(state="KS", fips=fl.get(F.norm_county(county)), county=county, race=key, party=p,
                                 candidate=htmlmod.unescape(name).strip(), vote_type="total",
                                 votes=float(votes.replace(",", "")), ts=ts, complete=done))
    return F._frame(rows)


def page_time(page: str) -> str | None:
    m = re.search(r"id\s*=\s*'time-stamp'\s*>\s*([^<]+)<", page)
    return m.group(1).strip() if m else None


def receive(state: str, page: str) -> dict:
    """Parse and keep a page sent from the browser. Returns a short summary for the sender."""
    if state != "KS":
        raise ValueError(f"no browser parser for {state}")
    df = parse_ks(page)
    info = dict(state=state, received=time.time(), page_time=page_time(page), counties=int(df["fips"].nunique()),
                votes=float(df["votes"].sum()), rows=len(df))
    if df.empty:
        info["error"] = "no Senate race found on this page: open the congressional results page (national.html)"
        return info
    with _lock:
        _latest[state] = dict(frame=df, **info)
    return info


def latest(state: str) -> dict | None:
    with _lock:
        return _latest.get(state)


def combined(state: str, fallback=None, max_age: float = 15 * 60):
    """A feed callable: the browser-sent page while it's recent (it covers every county),
    else the fallback adapter (Kansas: the big counties' own sites)."""
    def fn() -> pd.DataFrame:
        got = latest(state)
        if got and time.time() - got["received"] < max_age:
            return got["frame"]
        if fallback is not None:
            return fallback()
        return F._frame([])
    return fn


# The bookmark: posts the open page to the dashboard; if the browser refuses (the page's
# security policy or a local-network block), copies the page to the clipboard instead.
BOOKMARKLET = (
    "javascript:(()=>{const h=document.documentElement.outerHTML;"
    "const say=(m,ok)=>{const d=document.createElement('div');d.textContent=m;"
    "d.style.cssText='position:fixed;z-index:99999;top:12px;right:12px;padding:10px 14px;border-radius:8px;"
    "font:14px system-ui;color:#fff;background:'+(ok?'#1d7a3a':'#9a3412');document.body.appendChild(d);"
    "setTimeout(()=>d.remove(),6000)};"
    "say('Sending to dashboard... (first time only: if Chrome asks to allow local network access, click Allow)',true);"
    "fetch('http://127.0.0.1:PORT/ingest/ks',{method:'POST',headers:{'Content-Type':'text/plain'},body:h})"
    ".then(r=>r.json()).then(j=>say(j.error?j.error:'Sent to dashboard: '+j.counties+' counties, '"
    "+Math.round(j.votes).toLocaleString()+' votes',!j.error))"
    ".catch(()=>navigator.clipboard.writeText(h).then(()=>say('Browser blocked sending: page copied, paste it into the dashboard',false),"
    "()=>say('Could not send or copy; is the dashboard running?',false)))})()"
)


def bookmarklet(port: int = 8765) -> str:
    return BOOKMARKLET.replace("PORT", str(port))
