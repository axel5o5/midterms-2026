"""Michigan election-night feed, built from county results sites.

The state site (Michigan.gov/Vote = mvic.sos.state.mi.us) sits behind a
Cloudflare "Just a moment..." challenge, and the old mielections.us host times
out (both checked 2026-10-30), so there is no usable statewide feed. Instead:

  county     2024 pres total  host                                  2024 id  2026 id
  Oakland        771,939      Clarity ENR (detail.xml zip)          122321   127284
  Macomb         509,056      Clarity ENR                           122434   127293
  Genesee        223,203      Clarity ENR                           122430   127354
  Washtenaw      221,304      electionresults.ewashtenaw.org (HTML) nov2024  nov2026
  Ottawa         178,402      Clarity ENR                           123542   127391

about a third of Michigan's 2024 vote. Wayne (waynecountymi.gov: Akamai 403)
and Kent (kentcountymi.gov / accesskent.com: Cloudflare block) have no usable
results host and are not attempted.

Michigan quirks the generic Clarity parser (feeds.clarity_xml) doesn't handle:
- a county Clarity file has <Precinct> rows, not <County> rows, so every row
  gets the one county's FIPS here;
- "PRESIDENT" also matches village-president contests, and House contests are
  "Representative in Congress 9th District", so offices are matched with the
  MI-specific patterns in RACES;
- vote-type labels vary by county ("Absentee - Local", "Early Voting - Regional",
  "Precinct Votes", "Election"...) and are folded into mail / early /
  election_day, summed;
- Ottawa's and Washtenaw's files carry no party, so a per-race candidate ->
  party map (CANDIDATES) decides D/R; in races it doesn't list, those two
  counties' candidates are all O (House races included).

Sources live in data/live/mi_sources.json (county -> Clarity id or URL, or the
Washtenaw page URL) so ids can be pasted on the night. A county that fails is
skipped and its error kept in `last_errors`.

    uv run python -m midterms.live.feeds_mi            # 2026 feed, summary
    uv run python -m midterms.live.feeds_mi test2024   # 2024 presidential check
    uv run python -m midterms.live.feeds_mi list Ottawa
"""

from __future__ import annotations

import datetime as dt
import html
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from ..house import key as hkey
from ..snapshot import ROOT
from .feeds import COLS, _fips_lookup, _frame, _party, fetch   # county files have no <County> rows, so not clarity_xml
from .baselines import county_baseline, norm_county

CLARITY = "https://results.enr.clarityelections.com"
SOURCES_FILE = ROOT / "data" / "live" / "mi_sources.json"
MIN_INTERVAL = 45          # seconds between checks of any one county file

# Office text -> race key. House is handled separately (district number).
RACES = {
    "SEN-MI": r"^(UNITED STATES|U\.?\s?S\.?) SENAT",
    "GOV-MI": r"^GOVERNOR\s*(&|AND)\s*(LT|LIEUT)",   # not "Governor of Wayne State University"
}
HOUSE = r"(REPRESENTATIVE IN CONGRESS|U\.?\s?S\.? CONGRESS|UNITED STATES REPRESENTATIVE)\D*(\d+)"

# Per race: candidate name fragment (case-insensitive substring) -> party. It
# overrides the feed's party code and fills it in where the feed has none
# (Ottawa, Washtenaw). Races not listed keep the feed's party (O if none).
# Nominees per the 2026 general ballot (Washtenaw/Clarity files, 2026-10-30).
CANDIDATES = {
    "SEN-MI": {"El-Sayed": "D", "Rogers": "R"},
    "GOV-MI": {"Benson": "D", "John James": "R"},
}

# What to fill in for a 2024 presidential test run.
RACES_2024 = {"PRES-MI": r"^ELECTORS OF\s+PRESIDENT|^PRESIDENT\s*(&|AND)\s*VICE"}
CANDIDATES_2024 = {"PRES-MI": {"Harris": "D", "Trump": "R"}}
SOURCES_2024 = {
    "Oakland": {"clarity": 122321},
    "Macomb": {"clarity": 122434},
    "Genesee": {"clarity": 122430},
    "Washtenaw": {"washtenaw": "https://electionresults.ewashtenaw.org/electionreporting/nov2024/index.jsp"},
    "Ottawa": {"clarity": 123542},
}

NOT_VOTES = re.compile(r"^(rejected|unassigned) write-?ins?$", re.I)   # tallied lines that aren't votes for anyone

last_errors: dict[str, str] = {}


# ---- helpers ------------------------------------------------------------------------

def _vt(label: str) -> str:
    s = str(label).upper()
    if "ABSENTEE" in s or "MAIL" in s:
        return "mail"
    if "EARLY" in s:
        return "early"
    if "PROVISIONAL" in s:
        return "provisional"
    if "ELECTION" in s or "PRECINCT" in s:
        return "election_day"
    if "TOTAL" in s:
        return "total"
    return "other"


def _race_mi(office: str, races: dict[str, str], house: bool) -> str | None:
    o = re.sub(r"\s+", " ", office).strip().upper()
    for key, pat in races.items():
        if re.search(pat, o):
            return key
    if house:
        m = re.search(HOUSE, o)
        if m:
            return hkey("MI", int(m.group(2)))
    return None


def _party_mi(race: str, candidate: str, feed_party: str, candidates: dict[str, dict[str, str]]) -> str:
    c = str(candidate).lower()
    for name, p in (candidates.get(race) or {}).items():
        if name.lower() in c:
            return p
    return _party(feed_party) if feed_party else "O"


def _county_fips(county: str) -> str | None:
    return _fips_lookup("MI").get(norm_county(county))


def _clarity_id(spec) -> tuple[str | None, str]:
    """{'clarity': 127284} or {'clarity': 'https://results.enr.../MI/Oakland/127284/web.../'}
    -> (county from the URL or None, eid)."""
    v = str(spec)
    m = re.search(r"/MI/([^/]+)/(\d+)", v)
    return (m.group(1), m.group(2)) if m else (None, v.strip())


# ---- Clarity (one county per file) -------------------------------------------------------

def clarity_county_xml(county: str, xml_bytes: bytes, races: dict[str, str], candidates: dict[str, dict[str, str]],
                       house: bool = True) -> pd.DataFrame:
    root = ET.fromstring(xml_bytes)
    fips = _county_fips(county)
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for c in root.iter("Contest"):
        race = _race_mi(c.get("text", ""), races, house)
        if not race:
            continue
        # Clarity: precinctsReported = precincts counted, precinctsReporting = precincts in the contest
        done_n, total_n = c.get("precinctsReported"), c.get("precinctsReporting")
        done = bool(total_n) and total_n not in ("0",) and done_n == total_n
        for ch in c.iter("Choice"):
            name = re.sub(r"\s+", " ", ch.get("text", "")).strip()
            code = (ch.get("party") or "").strip()
            if code and name.upper().startswith(code.upper() + " "):     # Macomb: "DEM Abdul El-Sayed"
                name = name[len(code) + 1:]
            if NOT_VOTES.match(name):
                continue
            party = _party_mi(race, name, ch.get("party") or "", candidates)
            for vt in ch.iter("VoteType"):
                rows.append(dict(state="MI", fips=fips, county=county, race=race, party=party, candidate=name,
                                 vote_type=_vt(vt.get("name")), votes=vt.get("votes", 0), ts=ts, complete=done))
    return _sum(_frame(rows))


def clarity_county(county: str, eid, races=RACES, candidates=CANDIDATES, house: bool = True) -> pd.DataFrame:
    base = f"{CLARITY}/MI/{county}/{eid}"
    ver = fetch(f"{base}/current_ver.txt", min_interval=MIN_INTERVAL).decode().strip()
    z = zipfile.ZipFile(io.BytesIO(fetch(f"{base}/{ver}/reports/detailxml.zip", min_interval=MIN_INTERVAL,
                                         cache_name=f"MI_{county}_{eid}_detailxml.zip")))
    return clarity_county_xml(county, z.read("detail.xml"), races, candidates, house)


# ---- Washtenaw (electionresults.ewashtenaw.org, HTML summary page) ---------------------

def washtenaw_html(body: str, races: dict[str, str], candidates: dict[str, dict[str, str]], house: bool = True,
                   county: str = "Washtenaw") -> pd.DataFrame:
    def num(s):
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s else 0

    m_tot = re.search(r"Precincts Total:.*?>\s*([\d,]+)", body, re.S)
    m_done = re.search(r"Precincts Fully Counted:\s*(?:<[^>]+>\s*)*([\d,]+)", body, re.S)
    done = bool(m_tot and m_done) and num(m_tot.group(1)) > 0 and num(m_tot.group(1)) == num(m_done.group(1))
    fips = _county_fips(county)
    ts = dt.datetime.now(dt.UTC)
    head = ["early", "mail", "election_day"]          # Early / Absentee / Election Day / Total / Percent
    rows, race = [], None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S | re.I):
        if 'class="headertr"' in tr:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
            title = html.unescape(re.sub(r"<[^>]+>", " ", cells[0])) if cells else ""
            race = _race_mi(title, races, house)
            continue
        if race is None:
            continue
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if len(cells) < 5:
            continue
        name = re.sub(r"\s+", " ", cells[0].replace("\xa0", " ")).strip()
        if NOT_VOTES.match(name):
            continue
        party = _party_mi(race, name, "", candidates)
        for vt, v in zip(head, cells[1:4]):
            rows.append(dict(state="MI", fips=fips, county=county, race=race, party=party, candidate=name,
                             vote_type=vt, votes=num(v), ts=ts, complete=done))
    return _frame(rows)


def washtenaw(url: str, races=RACES, candidates=CANDIDATES, house: bool = True) -> pd.DataFrame:
    body = fetch(url, min_interval=MIN_INTERVAL, cache_name="MI_Washtenaw_index.html").decode("latin-1")
    return washtenaw_html(body, races, candidates, house)


# ---- assembly -------------------------------------------------------------------------

def _sum(df: pd.DataFrame) -> pd.DataFrame:
    """Fold several raw vote types that map to one (e.g. two absentee streams)."""
    if df.empty:
        return df
    keys = ["state", "fips", "county", "race", "party", "candidate", "vote_type"]
    g = df.groupby(keys, as_index=False, dropna=False).agg(votes=("votes", "sum"), ts=("ts", "max"),
                                                          complete=("complete", "all"))
    return g[COLS]


def load_sources(path=SOURCES_FILE) -> dict:
    """data/live/mi_sources.json; see that file for the format."""
    if not path.exists():
        raise RuntimeError(f"{path} not found: it maps each county to its Clarity id/URL or results page")
    cfg = json.loads(path.read_text())
    return {k: v for k, v in cfg.get("counties", cfg).items() if not k.startswith("_")}


def county_feed(county: str, spec: dict, races=RACES, candidates=CANDIDATES, house: bool = True) -> pd.DataFrame:
    if spec.get("clarity"):
        url_county, eid = _clarity_id(spec["clarity"])
        return clarity_county(url_county or county, eid, races, candidates, house)
    if spec.get("washtenaw"):
        return washtenaw(spec["washtenaw"], races, candidates, house)
    raise RuntimeError(f"{county}: no id/url filled in yet")


def mi(sources: dict | None = None, races: dict[str, str] | None = None,
       candidates: dict[str, dict[str, str]] | None = None, house: bool = True) -> pd.DataFrame:
    """Tidy MI frame from every configured county. A county that fails (not set,
    blocked, HTTP error, bad file) is skipped; see `last_errors`."""
    sources = load_sources() if sources is None else sources
    races = RACES if races is None else races
    candidates = CANDIDATES if candidates is None else candidates
    last_errors.clear()
    frames = []
    for county, spec in sources.items():
        if not spec or spec.get("skip"):
            continue
        try:
            frames.append(county_feed(county, spec, races, candidates, house))
        except Exception as e:  # noqa: BLE001 - one county must never break the rest
            last_errors[county] = f"{type(e).__name__}: {e}"
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True)[COLS] if frames else _frame([])


# ---- discovery --------------------------------------------------------------------------

def clarity_elections(county: str) -> pd.DataFrame:
    """A county's Clarity election list (EID, name, date). Clarity's elections.json is
    filled in for some counties only (Ottawa yes; Oakland, Macomb, Genesee return []);
    for the others the id is on the county clerk's page."""
    js = json.loads(fetch(f"{CLARITY}/MI/{county}/elections.json", min_interval=300, cache_name=f"MI_{county}_elections.json"))
    return pd.DataFrame(js, columns=["EID", "ElectionName", "Date"]) if js else pd.DataFrame(columns=["EID", "ElectionName", "Date"])


def clarity_check(county: str, eid) -> dict:
    """Confirm a pasted id: its election date, current version and when it last changed."""
    url_county, eid = _clarity_id(eid)
    county = url_county or county
    base = f"{CLARITY}/MI/{county}/{eid}"
    ver = fetch(f"{base}/current_ver.txt", min_interval=MIN_INTERVAL).decode().strip()
    s = json.loads(fetch(f"{base}/{ver}/json/en/electionsettings.json", min_interval=300,
                         cache_name=f"MI_{county}_{eid}_settings.json"))
    s = s.get("settings", s)
    return {"county": county, "eid": eid, "version": ver,
            "date": (s.get("electiondetails") or {}).get("electiondate"), "updated": s.get("websiteupdatedat")}


# ---- 2024 check -----------------------------------------------------------------------

def test_2024() -> pd.DataFrame:
    """Each source's 2024 presidential D/R totals against county_baseline("MI")."""
    df = mi(SOURCES_2024, RACES_2024, CANDIDATES_2024, house=False)
    got = (df[df["party"].isin(["D", "R"])].pivot_table(index=["fips", "county"], columns="party", values="votes",
                                                        aggfunc="sum").reset_index())
    alltot = df.groupby("fips")["votes"].sum().rename("feed_total")
    types = df.groupby("fips")["vote_type"].agg(lambda s: ",".join(sorted(set(s)))).rename("vote_types")
    b = county_baseline("MI").set_index("fips")[["pres2024_dem", "pres2024_gop", "pres2024_total"]]
    out = got.join(b, on="fips").join(alltot, on="fips").join(types, on="fips")
    out["d_diff"] = out["D"] - out["pres2024_dem"]
    out["r_diff"] = out["R"] - out["pres2024_gop"]
    out["total_diff"] = out["feed_total"] - out["pres2024_total"]
    return out


def _main(argv: list[str]) -> None:
    pd.set_option("display.width", 200)
    if argv and argv[0] == "test2024":
        print(test_2024().to_string(index=False))
    elif argv and argv[0] == "list":
        print(clarity_elections(argv[1]).to_string(index=False))
    elif argv and argv[0] == "check":
        print(clarity_check(argv[1], argv[2]))
    else:
        df = mi()
        if not df.empty:
            print(df.groupby(["county", "race", "party"])["votes"].sum().unstack("party").to_string())
    if last_errors:
        print("errors:", json.dumps(last_errors, indent=1))


if __name__ == "__main__":
    _main(sys.argv[1:])
