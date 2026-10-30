"""Nebraska election-night results (SEN-NE: Dan Osborn, independent, v Pete Ricketts).

The model reads every race as "the non-Republican minus the Republican", and the
non-Republican sits in the party="D" slot. Osborn is an independent (party code PET
on the state site, BYP or Pet in Sarpy's Clarity files), so he would land in "O" on
party codes alone. `NON_R` names the candidate who takes the D slot in each race;
every other non-Republican in that race goes to "O". Override it in
data/live/ne_sources.json ("non_r"). A race with an entry here fails loudly if no
candidate matches, rather than silently projecting Ricketts against nobody.

Sources (checked 2026-10-30), merged per (race, county): whichever has more votes
counted for that county wins, so a lagging source never drags a county backwards.

- state  electionresults.nebraska.gov, the Secretary of State's results site. Its
         JSON service (neresultswebservice.azurewebsites.us/ResultsAjax.svc) gives
         every race county by county, all 93 counties, with per-county precinct
         counts; no vote-type split. No robots.txt on either host and no bot wall.
         OFF BY DEFAULT: sos.nebraska.gov links the Nebraska.gov portal policies
         (nebraska.gov/policies), which forbid any "robot, bot, spider, scraper ...
         to monitor or copy ... data ... found on this Site or accessed through this
         Site" without prior written permission. The results site itself shows no
         terms. Turn on with "state_site": {"enabled": true} once that's settled.
         The 2026 race ids came from its Media CSV (`ne_discover()` re-reads them).
- sarpy  Sarpy County's Clarity ENR site (results.enr.clarityelections.com/NE/Sarpy),
         precinct detail.xml with Election Day / Early Voting / Provisional. ~11% of
         the state's 2024 vote. 2026 general EID 127564 (from its elections.json).
- Not usable: Douglas County Election Commission (votedouglascounty-ne.gov; its
  robots.txt disallows /meer/, where results live, and /elections/); Lancaster
  County (www.lancaster.ne.gov answers robots.txt with a Cloudflare 403 challenge);
  neither has a Clarity site. countyelectionresults.nebraska.gov only has PDFs.

2024 check (`ne_2024()`): state archive election 31, Senate race 12246/osn 102,
president 12465/osn 90 (ids from the 2024 night's pages in the Wayback Machine);
Sarpy EID 122854.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy

import pandas as pd

from ..snapshot import ROOT
from .baselines import norm_county, vote_type
from .feeds import COLS, _fips_lookup, _frame, _party, fetch

CONFIG = ROOT / "data" / "live" / "ne_sources.json"
STATE = "NE"
SITE = "https://electionresults.nebraska.gov"
SERVICE = "https://neresultswebservice.azurewebsites.us/ResultsAjax.svc"
CLARITY = "https://results.enr.clarityelections.com/NE"
MIN_INTERVAL = 30

# race -> name (any part, case-insensitive) of the candidate who takes the "D" slot
NON_R = {"SEN-NE": "Osborn"}

DEFAULTS = {
    "non_r": NON_R,
    "races": ["SEN-NE", "GOV-NE"],
    "state_site": {
        "enabled": False,
        "election_id": None,          # None = tonight's election; an id reads the archive (31 = 2024 general)
        # race -> [type, race id, office seq no], as on the site's Media CSV / BuildCounty() buttons
        "race_ids": {"SEN-NE": ["SW", 13224, 102], "GOV-NE": ["SW", 13508, 105]},
    },
    "counties": {
        "Sarpy": {"enabled": True, "eid": 127564},
    },
}

TEST_2024 = {
    "non_r": {"SEN-NE": "Osborn"},
    "races": ["SEN-NE", "PRES-NE"],
    "state_site": {"enabled": True, "election_id": 31,
                   "race_ids": {"SEN-NE": ["SW", 12246, 102], "PRES-NE": ["PRS", 12465, 90]}},
    "counties": {"Sarpy": {"enabled": True, "eid": 122854}},
}

status: dict[str, str] = {}                 # source -> "ok" or the last error, for a glance on the night
_last_good: dict[str, pd.DataFrame] = {}     # source + its settings -> last frame it returned, reused if it fails later


def _merge(base: dict, over: dict) -> dict:
    out = deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config() -> dict:
    """DEFAULTS overlaid with data/live/ne_sources.json (re-read on every call, so an
    edit on the night takes effect at the next poll)."""
    over = {}
    if CONFIG.exists():
        over = {k: v for k, v in json.loads(CONFIG.read_text()).items() if not k.startswith("_")}
    return _merge(DEFAULTS, over)


def race_key(office: str) -> str | None:
    """Office name on either source -> race key; None for offices we don't track.
    2024 had two Senate races: the 2-year special (Ricketts v Love) is left out."""
    o = re.sub(r"\s+", " ", office).upper()
    if "SENAT" in o and re.search(r"\b(US|U\.S\.|UNITED STATES)\b", o):
        return None if re.search(r"\b2 ?(YR|YEAR)", o) else "SEN-NE"
    if "PRESIDENT" in o:   # the per-district presidential contests are left out
        return None if "DISTRICT" in o else "PRES-NE"
    if re.match(r"(FOR )?GOVERNOR", o):
        return "GOV-NE"
    m = re.search(r"CONGRESS.*\bDIST(?:RICT|\.)?\s*(\d+)", o)
    if m:
        return f"NE-{int(m.group(1)):02d}"
    return None


def assign_slots(df: pd.DataFrame, non_r: dict[str, str]) -> pd.DataFrame:
    """Party slots from candidate names where `non_r` says so. Raises if a race with an
    entry has no matching candidate or no Republican (both would wreck the margin)."""
    df = df.copy()
    for race, name in non_r.items():
        m = df["race"] == race
        if not m.any():
            continue
        hit = df.loc[m, "candidate"].str.contains(name, case=False, regex=False)
        if not hit.any():
            raise RuntimeError(f"{race}: no candidate matching {name!r} for the D slot "
                               f"(found {sorted(df.loc[m, 'candidate'].unique())})")
        df.loc[m, "party"] = ["D" if h else ("R" if p == "R" else "O") for h, p in zip(hit, df.loc[m, "party"])]
    for race, g in df.groupby("race"):
        if not (g["party"] == "R").any():
            raise RuntimeError(f"{race}: no Republican found (party codes {sorted(g['party'].unique())})")
    return df


# ---- the Secretary of State's site ----------------------------------------------------

def state_url(rtype: str, race_id: int, osn: int, election_id: int | None = None) -> str:
    """The county breakdown the site's 'County Results' button loads (BuildCounties.js)."""
    q = f"type={rtype}&category=CTY&raceID={race_id}&osn={osn}&county=0&party=0"
    if election_id:
        return f"{SERVICE}/GetMapDataArchive?{q}&electionID={election_id}"
    return f"{SERVICE}/GetMapData?{q}"


def state_rows(items: list[dict], race: str, ts=None) -> list[dict]:
    """One race's GetMapData items -> tidy rows (party from the site's code; slots later).
    Live, the precinct counts are per county; in the archive they're statewide (all done)."""
    fl = _fips_lookup(STATE)
    ts = ts or dt.datetime.now(dt.UTC)
    return [dict(state=STATE, fips=fl.get(norm_county(x["CountyName"])), county=x["CountyName"], race=race,
                 party=_party(x.get("PartyCode") or ""), candidate=re.sub(r"\s+", " ", x["calcCandidate"]).strip(),
                 vote_type="total", votes=x.get("calcCandidateVotes") or 0, ts=ts,
                 complete=bool(x.get("TotalPrecincts")) and x.get("PrecinctsReporting") == x.get("TotalPrecincts"))
            for x in items]


def state_site(cfg: dict) -> pd.DataFrame:
    s = cfg["state_site"]
    rows = []
    for race in cfg["races"]:
        ids = s["race_ids"].get(race)
        if not ids:
            continue
        rtype, rid, osn = ids
        url = state_url(rtype, rid, osn, s.get("election_id"))
        items = json.loads(fetch(url, min_interval=MIN_INTERVAL, cache_name=f"ne_{race}_{rid}.json"))["d"]
        if not items:
            raise RuntimeError(f"{race}: state site returned nothing for race id {rid}/osn {osn}; "
                               "check race_ids in ne_sources.json (ne_discover() lists tonight's)")
        rows += state_rows(items, race)
    return _frame(rows)


def ne_discover() -> pd.DataFrame:
    """Tonight's statewide and congressional race ids from the site's Media CSVs
    (one request each), for pasting into ne_sources.json if they ever change."""
    out = []
    for t, m in (("SW", "CTY"), ("CG", "DIST")):
        body = fetch(f"{SITE}/resultsCSV.aspx?text=All&type={t}&map={m}", min_interval=MIN_INTERVAL, cache_name=f"ne_media_{t}.csv")
        d = pd.read_csv(io.BytesIO(body), dtype=str, index_col=False)
        d["race"] = d["RaceName"].map(race_key)
        d["type"] = t
        out.append(d.dropna(subset=["race"]).drop_duplicates("RaceID")[["race", "type", "RaceID", "OfficeSeqNo", "RaceName"]])
    return pd.concat(out, ignore_index=True)


# ---- Clarity county sites (Sarpy) -------------------------------------------------------

def clarity_county_xml(county: str, xml_bytes: bytes, races: list[str]) -> pd.DataFrame:
    """A county-level Clarity detail.xml (precincts, not counties) -> one county's rows."""
    root = ET.fromstring(xml_bytes)
    fips = _fips_lookup(STATE).get(norm_county(county))
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for c in root.iter("Contest"):
        race = race_key(c.get("text", ""))
        if race not in races:
            continue
        total, done = c.get("precinctsReporting"), c.get("precinctsReported")   # Clarity: total, then reported
        complete = bool(total) and total not in ("0",) and total == done
        for ch in c.iter("Choice"):
            for vt in ch.iter("VoteType"):
                rows.append(dict(state=STATE, fips=fips, county=county, race=race, party=_party(ch.get("party", "")),
                                 candidate=re.sub(r"\s+", " ", ch.get("text", "")).strip(), vote_type=vote_type(vt.get("name")),
                                 votes=vt.get("votes", 0), ts=ts, complete=complete))
    return _frame(rows)


def clarity_county(county: str, eid: int | str, races: list[str]) -> pd.DataFrame:
    base = f"{CLARITY}/{county}/{eid}"
    ver = fetch(f"{base}/current_ver.txt", min_interval=MIN_INTERVAL, cache_name=f"ne_{county}_{eid}_ver.txt").decode().strip()
    z = zipfile.ZipFile(io.BytesIO(fetch(f"{base}/{ver}/reports/detailxml.zip", min_interval=MIN_INTERVAL,
                                         cache_name=f"ne_{county}_{eid}_detailxml.zip")))
    return clarity_county_xml(county, z.read("detail.xml"), races)


# ---- entry point ------------------------------------------------------------------------

def _sources(cfg: dict) -> dict:
    """name -> (cache key, fetch-and-parse function) for every enabled source."""
    out = {}
    s = cfg["state_site"]
    if s.get("enabled"):
        out["state"] = (f"state:{s.get('election_id')}:{json.dumps(s['race_ids'], sort_keys=True)}", lambda: state_site(cfg))
    for county, c in cfg.get("counties", {}).items():
        if c.get("enabled") and c.get("eid"):
            out[county] = (f"{county}:{c['eid']}", lambda county=county, eid=c["eid"]: clarity_county(county, eid, cfg["races"]))
    return out


def merge(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per (race, county), keep the source with the most votes counted (ties: first listed)."""
    frames = {k: f for k, f in frames.items() if len(f)}
    if not frames:
        return _frame([])
    df = pd.concat([f.assign(_src=k, _order=i) for i, (k, f) in enumerate(frames.items())], ignore_index=True)
    tot = df.groupby(["race", "fips", "_src", "_order"], as_index=False)["votes"].sum()
    best = tot.sort_values(["votes", "_order"], ascending=[False, True]).drop_duplicates(["race", "fips"])
    keep = df.merge(best[["race", "fips", "_src"]], on=["race", "fips", "_src"])
    return keep[COLS].reset_index(drop=True)


def ne(cfg: dict | None = None) -> pd.DataFrame:
    """Tidy Nebraska results from every enabled source. A source that fails keeps its
    last good frame (and its error in `status`); only if nothing has ever worked does
    this raise, so the dashboard shows why."""
    cfg = cfg or config()
    srcs = _sources(cfg)
    if not srcs:
        raise RuntimeError("no Nebraska source enabled (data/live/ne_sources.json)")
    frames, errors = {}, []
    for name, (key, fn) in srcs.items():
        try:
            f = assign_slots(fn(), cfg.get("non_r", {}))
            f = f[f["race"].isin(cfg["races"])]
            _last_good[key], status[name] = f, "ok"
        except Exception as e:  # one source failing must not take the others down
            status[name] = f"{type(e).__name__}: {e}"[:300]
            errors.append(f"{name}: {status[name]}")
        if key in _last_good:
            frames[name] = _last_good[key]
    if not frames:
        raise RuntimeError("; ".join(errors))
    return merge(frames)


def ne_2024() -> pd.DataFrame:
    """The same path on the 2024 general (Osborn v Fischer, Harris v Trump)."""
    return ne(TEST_2024)
