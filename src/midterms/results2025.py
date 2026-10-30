"""2025 governor results (Virginia, New Jersey) by county, and the swing from 2024.

Output: data/history/gov2025_county.csv, one row per county / county-equivalent
(VA 133 = 95 counties + 38 independent cities; NJ 21), with
fips, state, county, dem, rep, other, total, margin25, margin24, swing, source.
Margins are D minus R as points of all governor votes in the unit (write-ins
and minor parties included in `total`); swing = margin25 - margin24, where
margin24 is the 2024 presidential margin from `live.baselines.county_baseline`.

Sources (official, certified; fetched 2026-10-30, raw copies in
data/history/raw_2025/):
- Virginia: Department of Elections ENR site, "2025 November General"
  (isOfficialResults=true, published 2025-12-01). Election metadata from
  https://enr.elections.virginia.gov/results/public/api/elections/virginia/2025-November-General
  lists the public reports; the "Election Results" CSV (precinct-level, every
  contest) is served from https://enr.elections.virginia.gov/cdn/results/<jurisdictionId>/<blobName>.
  LocalityCode is the county FIPS suffix. Write-ins are in `WriteInVote` on
  the "WRITE IN VOTES" rows and go to `other`.
- New Jersey: Division of Elections, "Official List, Candidates for Governor,
  General Election 11/04/2025" (dated 12/03/2025),
  https://www.nj.gov/state/elections/assets/pdf/election-results/2025/2025-official-general-results-governor.pdf
  Read with poppler's `pdftotext -layout` (must be on PATH). The certified
  list has no write-in tally, so NJ `other` is Libertarian + Socialist Workers.

robots.txt (checked 2026-10-30): enr.elections.virginia.gov has none (404);
www.nj.gov disallows only paths outside /state/elections/. Neither names
AI crawlers (feeds.CRAWLER_AGENTS). Not used: www.elections.virginia.gov
disallows *.csv/*.json for all agents (the ENR host above is separate);
Wikipedia's robots.txt disallows /w/ (so the action=parse API) for all agents.
The certified statewide totals below were cross-checked once against the
Wikipedia articles' /wiki/ pages (an allowed path); build() does not fetch them.

Downloaded files are untrusted: they are only read as data. Run build() under
`uv run python -I -c "from midterms.results2025 import build; build()"`.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import quote, urlsplit

import pandas as pd
import requests

from .live.baselines import county_baseline, norm_county
from .snapshot import ROOT

RAW = ROOT / "data" / "history" / "raw_2025"
OUT = ROOT / "data" / "history" / "gov2025_county.csv"
UA = "midterms-2026/0.1 (personal election research; low volume)"
from .live.feeds import CRAWLER_AGENTS as BLOCKED_AGENTS  # AI-crawler user agents honoured in robots.txt

VA_ENR = "https://enr.elections.virginia.gov"
VA_ELECTION = f"{VA_ENR}/results/public/api/elections/virginia/2025-November-General"
NJ_PDF = ("https://www.nj.gov/state/elections/assets/pdf/election-results/2025/"
          "2025-official-general-results-governor.pdf")

VA_SOURCE = "VA Dept of Elections ENR, certified Election Results CSV (published 2025-12-01)"
NJ_SOURCE = "NJ Division of Elections, Official List: Governor, General 11/04/2025 (dated 2025-12-03)"

# Certified statewide totals (dem, rep, other, total). VA: ENR certified data,
# matching Wikipedia's table; NJ: the "Total" lines of the official list.
CERTIFIED = {
    "VA": (1_976_857, 1_449_586, 6_897, 3_433_340),
    "NJ": (1_896_610, 1_417_705, 11_880 + 8_164, 3_334_359),
}
COUNTIES = {"VA": 133, "NJ": 21}


# --- fetching -------------------------------------------------------------

def _allowed(url: str) -> bool:
    """True unless the host's robots.txt disallows any of BLOCKED_AGENTS for this URL.

    urllib's parser ignores wildcard rules like `Disallow: *.csv`; fine for the
    two hosts used here (neither has any), but don't reuse this for others blindly.
    """
    parts = urlsplit(url)
    r = requests.get(f"{parts.scheme}://{parts.netloc}/robots.txt", headers={"User-Agent": UA}, timeout=30)
    if r.status_code in (401, 403):
        return False
    if r.status_code >= 400:          # no robots.txt: no restrictions
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return all(rp.can_fetch(agent, url) for agent in BLOCKED_AGENTS)


def _fetch(url: str, name: str, refresh: bool) -> Path:
    path = RAW / name
    if path.exists() and not refresh:
        return path
    if not _allowed(url):
        raise PermissionError(f"robots.txt disallows {url}")
    time.sleep(1.0)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    time.sleep(1.0)
    return path


# --- parsing --------------------------------------------------------------

def _va(refresh: bool) -> pd.DataFrame:
    meta = json.loads(_fetch(VA_ELECTION, "va_enr_election.json", refresh).read_text())
    if not meta.get("isOfficialResults"):
        raise ValueError("VA ENR results are not marked official")
    blob = next(rep["blobName"] for cat in meta["publicReportCategories"] for rep in cat["reports"]
                if rep["reportName"] == "Election Results")
    url = f"{VA_ENR}/cdn/results/{meta['jurisdictionId']}/{quote(blob)}"
    d = pd.read_csv(_fetch(url, "va_enr_election_results.csv", refresh), dtype=str)
    g = d[d["OfficeTitle"] == "Governor"].copy()
    votes = pd.to_numeric(g["TOTAL_VOTES"]).fillna(0)
    write_in = g["CandidateName"].str.upper().eq("WRITE IN VOTES")
    g["v"] = votes.where(~write_in, pd.to_numeric(g["WriteInVote"]).fillna(0))
    g["col"] = g["Party"].map({"Democratic": "dem", "Republican": "rep"}).fillna("other")
    out = g.pivot_table(index=["LocalityCode", "LocalityName"], columns="col", values="v",
                        aggfunc="sum", fill_value=0).reset_index()
    out["fips_src"] = "51" + out["LocalityCode"].str.zfill(3)
    return out.rename(columns={"LocalityName": "name"}).assign(state="VA", source=VA_SOURCE)


_NJ_ROW = re.compile(r"^\s{20,}([A-Z][A-Z ]*?)\s+(DEMOCRATIC|REPUBLICAN|LIBERTARIAN PARTY|SOCIALIST WORKERS PARTY)"
                     r"\s+([\d,]+)\s*$")
_NJ_TOTAL = re.compile(r"^\s+Total\s+([\d,]+)\s*$")


def _nj(refresh: bool) -> pd.DataFrame:
    pdf = _fetch(NJ_PDF, "nj_2025-official-general-results-governor.pdf", refresh)
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True,
                          check=True, timeout=60).stdout
    rows, totals, block = [], [], []
    for line in text.splitlines():
        if m := _NJ_ROW.match(line):
            party = m.group(2)
            col = {"DEMOCRATIC": "dem", "REPUBLICAN": "rep"}.get(party, "other")
            block.append((m.group(1).strip(), col, party, int(m.group(3).replace(",", ""))))
        elif (m := _NJ_TOTAL.match(line)) and block:
            stated = int(m.group(1).replace(",", ""))
            if sum(b[3] for b in block) != stated:
                raise ValueError(f"NJ {block[0][2]}: counties sum to {sum(b[3] for b in block)}, list says {stated}")
            totals.append((block[0][2], stated))
            rows += block
            block = []
    if block:
        raise ValueError("NJ: a candidate block had no Total line")
    d = pd.DataFrame(rows, columns=["name", "col", "party", "v"])
    if d.groupby("party")["name"].nunique().ne(COUNTIES["NJ"]).any():
        raise ValueError(f"NJ: expected {COUNTIES['NJ']} counties per candidate")
    out = d.pivot_table(index="name", columns="col", values="v", aggfunc="sum", fill_value=0).reset_index()
    return out.assign(state="NJ", fips_src=pd.NA, source=NJ_SOURCE)


def _join(res: pd.DataFrame, state: str) -> pd.DataFrame:
    b = county_baseline(state)[["fips", "county", "key", "margin24"]]
    # VA writes "KING & QUEEN COUNTY"; the baseline has "King and Queen County"
    res = res.assign(key=res["name"].str.replace("&", " AND ", regex=False).map(norm_county))
    if res["key"].duplicated().any() or b["key"].duplicated().any():
        raise ValueError(f"{state}: duplicate county keys")
    m = res.merge(b, on="key", how="outer", indicator=True, validate="one_to_one")
    if (m["_merge"] != "both").any() or len(m) != COUNTIES[state]:
        bad = m.loc[m["_merge"] != "both", ["name", "county", "_merge"]]
        raise ValueError(f"{state}: {len(m)} rows, unmatched:\n{bad}")
    if state == "VA" and (m["fips_src"] != m["fips"]).any():
        raise ValueError("VA: name match disagrees with the source's FIPS code")
    return m


def build(refresh: bool = False) -> pd.DataFrame:
    """Fetch (or reuse the cached raw files), rebuild and write gov2025_county.csv.

    refresh=True re-downloads the raw files even if cached.
    """
    parts = []
    for state, res in (("VA", _va(refresh)), ("NJ", _nj(refresh))):
        m = _join(res, state)
        for c in ("dem", "rep", "other"):
            m[c] = m.get(c, 0)
            m[c] = m[c].astype(int)
        m["total"] = m[["dem", "rep", "other"]].sum(axis=1)
        got = tuple(int(m[c].sum()) for c in ("dem", "rep", "other", "total"))
        if got != CERTIFIED[state]:
            raise ValueError(f"{state}: county sums {got} != certified {CERTIFIED[state]}")
        parts.append(m)
    d = pd.concat(parts, ignore_index=True)
    d["margin25"] = 100 * (d["dem"] - d["rep"]) / d["total"]
    d["swing"] = d["margin25"] - d["margin24"]
    d = d[["fips", "state", "county", "dem", "rep", "other", "total", "margin25", "margin24", "swing", "source"]]
    d = d.sort_values("fips").reset_index(drop=True)
    d.round({"margin25": 3, "margin24": 3, "swing": 3}).to_csv(OUT, index=False)
    return county_swing()


def county_swing(state: str | None = None) -> pd.DataFrame:
    """Read gov2025_county.csv (optionally one state: 'VA' or 'NJ')."""
    d = pd.read_csv(OUT, dtype={"fips": str})
    return d[d["state"] == state].reset_index(drop=True) if state else d


if __name__ == "__main__":
    print(build())
