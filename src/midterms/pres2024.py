"""Where the 2024 presidential polls missed, state by state.

A state's polling miss in a presidential year has carried into the next
midterm: regressing a state's Senate/governor miss on its presidential miss two
years earlier (both net of the year's national miss) gives a slope of 0.34
(se 0.08) over 2000-2022 and 0.54 (se 0.11) for 2016->18 and 2020->22.

Polls: Wikipedia's "Statewide opinion polling for the 2024 United States
presidential election", first head-to-head Harris-Trump table per state,
averaged over polls ending 2024-10-15..11-05 (same window as the history).
Results: data/reference/pres_2024_by_state.csv.
"""

from __future__ import annotations

import io
import json
import re
import time

import pandas as pd
import requests

from .senate import NAME_TO_ABB
from .snapshot import ROOT

API = "https://en.wikipedia.org/w/api.php"
PAGE = "Statewide opinion polling for the 2024 United States presidential election"
CACHE = ROOT / "data" / "history" / "wikipedia_2024_polls"
OUT = ROOT / "data" / "history" / "pres2024_state_miss.csv"
_h = {"User-Agent": "Mozilla/5.0 (personal election research; low volume)"}

PERSISTENCE = 0.34          # all six presidential->midterm pairs since 2000
PERSISTENCE_RECENT = 0.54   # 2016->18 and 2020->22 only


def _api(params: dict) -> dict:
    """Cached responses only. These were fetched from Wikipedia's API (/w/api.php) on
    2026-10-29; its robots.txt disallows /w/ for every crawler, so nothing new is fetched."""
    key = re.sub(r"[^A-Za-z0-9]+", "_", json.dumps(params, sort_keys=True))[:120]
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    raise RuntimeError(f"not cached, and Wikipedia's robots.txt disallows the API: {params}")
    for i in range(6):
        r = requests.get(API, params={**params, "format": "json", "formatversion": 2}, headers=_h, timeout=60)
        if r.status_code == 200 and r.text.lstrip().startswith("{"):
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(r.text)
            time.sleep(1.0)
            return r.json()
        time.sleep(5 * (i + 1))
    r.raise_for_status()
    raise RuntimeError(f"Wikipedia API kept failing: {r.status_code}")


def _end_date(s: str) -> pd.Timestamp:
    s = re.sub(r"\[.*?\]", "", s)
    m = re.findall(r"([A-Z][a-z]+)\s*(\d{1,2})?(?:\s*[–-]\s*(?:([A-Z][a-z]+)\s*)?(\d{1,2}))?,?\s*(\d{4})", s)
    if not m:
        return pd.NaT
    mon1, d1, mon2, d2, yr = m[-1]
    return pd.to_datetime(f"{mon2 or mon1} {d2 or d1 or '1'} {yr}", errors="coerce")


def state_polls() -> pd.DataFrame:
    secs = _api({"action": "parse", "page": PAGE, "prop": "sections", "redirects": 1})["parse"]["sections"]
    rows = []
    for s in secs:
        name = s["line"]
        if name == "Statewide":
            st = "ME"  # Maine's statewide subsection
        elif name in NAME_TO_ABB and name != "Maine":
            st = NAME_TO_ABB[name]
        else:
            continue
        html = _api({"action": "parse", "page": PAGE, "prop": "text", "section": s["index"]})["parse"]["text"]
        try:
            tabs = pd.read_html(io.StringIO(html))
        except ValueError:
            continue
        for t in tabs:
            t.columns = [" ".join(dict.fromkeys(map(str, c))) if isinstance(c, tuple) else str(c) for c in t.columns]
            tc = next((c for c in t.columns if "Trump" in c), None)
            hc = next((c for c in t.columns if "Harris" in c), None)
            dc = next((c for c in t.columns if "Date" in c), None)
            if not (tc and hc and dc):
                continue
            num = lambda x: pd.to_numeric(x.astype(str).str.extract(r"(\d+(?:\.\d+)?)")[0], errors="coerce")
            rows.append(pd.DataFrame({"state": st, "dates": t[dc].astype(str), "trump": num(t[tc]),
                                      "harris": num(t[hc]), "source": t[t.columns[0]].astype(str)}))
            break
    polls = pd.concat(rows, ignore_index=True).dropna(subset=["trump", "harris"])
    polls["end"] = polls["dates"].map(_end_date)
    return polls


def state_miss(write: bool = True) -> pd.DataFrame:
    polls = state_polls()
    final = polls[(polls["end"] >= "2024-10-15") & (polls["end"] <= "2024-11-05")]
    avg = final.groupby("state").agg(poll_d_margin=("harris", "mean"), n=("harris", "size"))
    avg["poll_d_margin"] = final.assign(m=final["harris"] - final["trump"]).groupby("state")["m"].mean()
    res = pd.read_csv(ROOT / "data" / "reference" / "pres_2024_by_state.csv").set_index("state")["d_margin_2024"]
    avg["actual"] = res
    avg["miss"] = avg["actual"] - avg["poll_d_margin"]          # + = Harris beat her polls
    avg["miss_vs_national"] = avg["miss"] - avg["miss"].mean()  # what carries over
    if write:
        avg.round(3).to_csv(OUT)
    return avg
