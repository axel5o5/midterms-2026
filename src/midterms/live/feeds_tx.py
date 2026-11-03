"""Texas election-night feed, built from county Clarity results sites.

Texas moved its statewide election-night results off results.texas-election.com (its
election list stops at the 2024 general) to goelect.txelections.civixapps.com, the site
sos.state.tx.us/elections/index.shtml links (checked 2026-11-02). That host's robots.txt
disallows the AI-crawler user agents this tool honours (CRAWLER_AGENTS) for every path,
so it isn't used. `feeds.tx()` still reads the old host, for the 2024 replay.

Instead, the counties that run their own Clarity ENR sites (no robots.txt there):

  county       2024 pres total  share of TX  2024 id  2026 id
  Harris         1,556,310        13.7%      1124     1126     own results JSON (harris())
  Dallas           848,948         7.5%      122494   127396
  Tarrant          822,680         7.2%      122489   127297
  Denton           448,729         3.9%      122426   127398
  Fort Bend        362,259         3.2%      122596   127480
  Williamson       308,163         2.7%         -     127488
  El Paso          251,371         2.2%      122595   127348
                                  40.4%
  Travis           580,285         5.1%      122432   not posted yet (2026-11-02)

The 2026 ids come from each county's Clarity elections.json
(results.enr.clarityelections.com/TX/<County>/elections.json) or its elections page;
each source is noted in tx_sources.json. Harris runs its own results JSON
(appfiles.harrisvotes.com, election code from app.harrisvotes.com's results page), read
by harris(). The other big counties (Bexar, Collin, Montgomery, Hidalgo) post PDFs or
CSVs only. Sources live in
data/live/tx_sources.json (county -> Clarity id or URL), re-read on every call, so an id
can be pasted on the night. A county that fails keeps its last good rows and turns the
dashboard's TX chip amber ("partial", with the error); if no county can be read at all,
`tx_counties()` raises. Each file must be the 11/3/2026 election and the county it's
listed under (its <Region>), or it is refused.

Texas's 2022 baseline has no vote-type breakdown, and mail here ran 23-44 points more
Democratic than its county in 2024, so a county keeps its early / mail / Election Day
split only where data/reference/vote_type_leans_2024.csv has that county's measured
2024 leans (all but Williamson, which is folded into one total).

Texas county quirks:
- a county file has <Precinct> rows, not <County> rows, so every row gets that county's
  FIPS (as in Michigan);
- vote-type labels differ by county ("Early", "Early Voting In-Person", "Early Voting
  Provisionals", "Ballot by Mail", "ED Provisional"...) and are folded into early /
  mail / election_day / provisional, summed;
- city races such as "City of El Paso, Representative, Dist 1" must not read as House
  races: only offices starting "US"/"United States" count (feeds._race);
- Travis's file writes party="(D)" and text="(D) Colin Allred"; the parentheses are
  dropped and the prefix stripped from the name. Its final 2024 file still says 142 of 287 precincts reported, so expect
  Travis never to show as complete; its 2024 totals are within 13 votes of the baseline.

    uv run python -m midterms.live.feeds_tx            # 2026 feed, summary
    uv run python -m midterms.live.feeds_tx test2024   # 2024 presidential check vs county_baseline
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache

import pandas as pd

from ..snapshot import ROOT
from .baselines import REF, county_baseline, norm_county
from .feeds import COLS, _fips_lookup, _frame, _party, _race, _rel, fetch, same_date
from .feeds_mi import NOT_VOTES, _sum

CLARITY = "https://results.enr.clarityelections.com"
SOURCES_FILE = ROOT / "data" / "live" / "tx_sources.json"
MIN_INTERVAL = 45          # seconds between checks of any one county file
ELECTION_DATE = "11/3/2026"

# Candidate name fragment -> party, per race: fills in a missing party code and overrides
# a wrong one. Nominees per the 2026 county files (Denton, El Paso, Williamson; 2026-11-02).
CANDIDATES = {
    "SEN-TX": {"Talarico": "D", "Paxton": "R"},
    "GOV-TX": {"Hinojosa": "D", "Abbott": "R"},
}
CANDIDATES_2024 = {"PRES-TX": {"Harris": "D", "Trump": "R"}}
SOURCES_2024 = {"Denton": {"clarity": 122426}, "El Paso": {"clarity": 122595}, "Travis": {"clarity": 122432}}

_NOT_A_VOTE_TYPE = re.compile(r"regvoters|overvote|undervote", re.I)

last_errors: dict[str, str] = {}
_last_good: dict[str, tuple[float, str, pd.DataFrame]] = {}   # county -> (time, id it came from, frame)


def _vt(label: str) -> str | None:
    """County vote-type label -> early / mail / election_day / provisional; None for the
    per-contest tallies that aren't votes (registered voters, over/undervotes)."""
    s = str(label).upper()
    if _NOT_A_VOTE_TYPE.search(s):
        return None
    if "PROVISIONAL" in s or re.match(r"^PROV\b", s):   # Dallas: "PROV/EV/ED"
        return "provisional"
    if "ABSENTEE" in s or "MAIL" in s:
        return "mail"
    if "EARLY" in s or re.match(r"^EV\b", s):
        return "early"
    if "ELECTION" in s or re.match(r"^ED\b", s):
        return "election_day"
    if "TOTAL" in s:
        return "total"
    return "other"


def _party_tx(race: str, candidate: str, feed_party: str, candidates: dict[str, dict[str, str]]) -> str:
    c = str(candidate).lower()
    for name, p in (candidates.get(race) or {}).items():
        if name.lower() in c:
            return p
    return _party(feed_party) if feed_party else "O"


def county_xml(county: str, xml_bytes: bytes, candidates: dict[str, dict[str, str]] | None = None,
               expect_date: str | None = None) -> pd.DataFrame:
    """One county's Clarity detail.xml -> tidy rows (county totals per candidate x vote type)."""
    candidates = CANDIDATES if candidates is None else candidates
    root = ET.fromstring(xml_bytes)
    if expect_date:
        got = (root.findtext("ElectionDate") or "").strip()
        if not same_date(got, expect_date):
            raise RuntimeError(f"TX {county}: file is {root.findtext('ElectionName')!r} dated {got!r}, not "
                               f"{expect_date}: wrong id in {_rel(SOURCES_FILE)}?")
    region = (root.findtext("Region") or "").strip()
    if region and norm_county(region) != norm_county(county):   # an id pasted under the wrong county
        raise RuntimeError(f"TX {county}: the file is {region} County's: wrong id in {_rel(SOURCES_FILE)}?")
    fips = _fips_lookup("TX").get(norm_county(county))
    if fips is None:
        raise RuntimeError(f"TX {county}: not a Texas county name (check {_rel(SOURCES_FILE)})")
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for c in root.iter("Contest"):
        race = _race("TX", c.get("text", ""))
        if not race:
            continue
        # Clarity: precinctsReported = precincts counted, precinctsReporting = precincts in the contest
        done_n, total_n = c.get("precinctsReported"), c.get("precinctsReporting")
        done = bool(total_n) and total_n != "0" and done_n == total_n
        for ch in c.iter("Choice"):
            name = re.sub(r"\s+", " ", ch.get("text", "")).strip()
            feed_party = re.sub(r"[()\s]", "", ch.get("party") or "")   # Travis: party="(D)"
            m = re.match(r"^\(([A-Za-z]{1,3})\)\s*(.+)$", name)          # ...and text="(D) Colin Allred"
            if m:
                feed_party = feed_party or m.group(1)
                name = m.group(2)
            if feed_party and name.upper().startswith(feed_party.upper() + " "):   # Fort Bend: "DEM JAMES TALARICO"
                name = name[len(feed_party) + 1:]
            if NOT_VOTES.match(name):
                continue
            party = _party_tx(race, name, feed_party, candidates)
            counted = 0.0
            for vt in ch.iter("VoteType"):
                t = _vt(vt.get("name"))
                if t is None:
                    continue
                counted += float(vt.get("votes", 0) or 0)
                rows.append(dict(state="TX", fips=fips, county=f"{county} County", race=race, party=party,
                                 candidate=name, vote_type=t, votes=vt.get("votes", 0), ts=ts, complete=done))
            total = ch.get("totalVotes")
            if total not in (None, "") and abs(float(total) - counted) > 0.5:   # every vote lands in some type
                raise RuntimeError(f"TX {county}: {race} {name}: vote types add to {counted:,.0f}, the file's "
                                   f"total is {float(total):,.0f} (a vote-type label this parser drops?)")
    if not any(r["race"] == "SEN-TX" for r in rows):
        raise RuntimeError(f"TX {county}: no U.S. Senate rows in detail.xml (file layout changed?)")
    return _fit_types(_sum(_frame(rows)))


@lru_cache(maxsize=1)
def _lean_types() -> dict[str, set[str]]:
    """fips -> vote types with a measured 2024 lean (data/reference/vote_type_leans_2024.csv)."""
    p = REF / "vote_type_leans_2024.csv"
    if not p.exists():
        return {}
    lv = pd.read_csv(p, dtype={"fips": str})
    lv = lv[lv["state"] == "TX"]
    return {f: set(g["vote_type"]) for f, g in lv.groupby("fips")}


def _fit_types(df: pd.DataFrame) -> pd.DataFrame:
    """Match a county's vote types to the ones its baseline has measured leans for.

    Texas's 2022 baseline has no breakdown, and mail ran 23-44 points more Democratic than
    its county in 2024, so an unleaned mail row would read as county swing. So:
    - a candidate's 'total' row is dropped where the same candidate also has split rows
      (no double count), and kept where it has none;
    - a provisional row in a county without a provisional lean joins Election Day;
    - a county with no measured leans, or with any other unmeasured type, is folded into
      one 'total' row per candidate. A county *with* leans folding is unexpected, so it is
      noted in attrs["note"] (the feed shows as partial)."""
    if df.empty:
        return df
    keys = ["fips", "race", "candidate"]
    has_split = df[df["vote_type"] != "total"].groupby(keys).size()
    split_idx = pd.MultiIndex.from_frame(df[keys])
    df = df[(df["vote_type"] != "total") | ~split_idx.isin(has_split.index)]
    out, notes = [], []
    for fips, g in df.groupby("fips", sort=False):
        known = _lean_types().get(fips, set())
        if "provisional" not in known and "election_day" in known:
            g = _sum(g.assign(vote_type=g["vote_type"].replace({"provisional": "election_day"})))
        types = set(g["vote_type"])
        if types <= known or types == {"total"}:
            out.append(g)
            continue
        if known:
            notes.append(f"{g['county'].iloc[0]} reports {sorted(types - known)} with no measured lean: counted as totals")
        out.append(_sum(g.assign(vote_type="total")))
    res = pd.concat(out, ignore_index=True)[COLS]
    if notes:
        res.attrs["note"] = "; ".join(notes)
    return res


def _clarity_id(county: str, spec) -> tuple[str, str]:
    """{'clarity': 127398} or a results.enr... URL with /TX/<County>/<eid>/ -> (url county, eid)."""
    v = str(spec).strip()
    m = re.search(r"/TX/([^/]+)/(\d+)", v)
    return (m.group(1), m.group(2)) if m else (county.replace(" ", "_"), v)


def clarity_county(county: str, eid, candidates=None, expect_date: str | None = ELECTION_DATE) -> pd.DataFrame:
    url_county, eid = _clarity_id(county, eid)
    base = f"{CLARITY}/TX/{url_county}/{eid}"
    ver = fetch(f"{base}/current_ver.txt", min_interval=MIN_INTERVAL).decode().strip()
    z = zipfile.ZipFile(io.BytesIO(fetch(f"{base}/{ver}/reports/detailxml.zip", min_interval=MIN_INTERVAL,
                                         cache_name=f"TX_{url_county}_{eid}_detailxml.zip")))
    return county_xml(county, z.read("detail.xml"), candidates, expect_date)


# ---- Harris (its own results JSON) ----------------------------------------------------

HARRIS = "https://appfiles.harrisvotes.com/harrisvotes/prd/Data"
# per contest, per candidate: ab = mail (absentee), ev = early, ed = Election Day, tv = total.
# tv runs ~0.1-0.2% above ab+ev+ed (2024: Trump 722,695 vs 721,887); that remainder isn't
# broken out, so it is kept as 'provisional' and no vote is lost.
_HARRIS_TYPES = {"ab": "mail", "ev": "early", "ed": "election_day"}


def harris_json(body: bytes, candidates: dict[str, dict[str, str]] | None = None,
                expect_date: str | None = None, code: str | None = None) -> pd.DataFrame:
    """Harris County's resultsbyballot.json -> tidy rows (county totals per candidate x vote type)."""
    candidates = CANDIDATES if candidates is None else candidates
    d = json.loads(body.decode("utf-8-sig"))
    if code is not None and str(d.get("ec")) != str(code):
        raise RuntimeError(f"TX Harris: file is election {d.get('ec')!r}, not {code}")
    if expect_date:
        try:
            got = dt.datetime.strptime(str(d.get("edt", "")).strip(), "%B %d, %Y").strftime("%-m/%-d/%Y")
        except ValueError:
            got = str(d.get("edt"))
        if not same_date(got, expect_date):
            raise RuntimeError(f"TX Harris: file is {d.get('et')!r} dated {d.get('edt')!r}, not {expect_date}: "
                               f"wrong code in {_rel(SOURCES_FILE)}?")
    fips = _fips_lookup("TX").get(norm_county("Harris"))
    ts = dt.datetime.now(dt.UTC)
    rows, seen, notes = [], {}, []
    for c in d.get("contests") or []:
        title = str(c.get("t", ""))
        race = _race("TX", title)
        if not race or re.search(r"unexpired|special", title, re.I):   # 2024: "District 18 - Unexpired Term"
            continue
        if race in seen:   # two contests for one seat: keep the first, say so
            notes.append(f"Harris: {title!r} also maps to {race}, ignored (kept {seen[race]!r})")
            continue
        seen[race] = title
        cols = {k: c.get(k) for k in ("ca", *_HARRIS_TYPES, "tv")}
        n = len(cols["ca"] or [])
        if not n or any(not isinstance(v, list) or len(v) != n for v in cols.values()):
            raise RuntimeError(f"TX Harris: {title!r}: candidate and vote arrays missing or of different lengths "
                               f"({ {k: len(v) if isinstance(v, list) else v for k, v in cols.items()} })")
        try:
            nums = {k: [float(x) for x in cols[k]] for k in (*_HARRIS_TYPES, "tv")}
        except (TypeError, ValueError) as e:
            raise RuntimeError(f"TX Harris: {title!r}: a vote count isn't a number ({e})") from e
        if any(not (x >= 0 and x < 1e9) for v in nums.values() for x in v):
            raise RuntimeError(f"TX Harris: {title!r}: negative or impossible vote count")
        try:
            done = int(c.get("tp")) > 0 and int(c.get("pr")) == int(c.get("tp"))
        except (TypeError, ValueError):
            done = False
        for i, label in enumerate(cols["ca"]):
            m = re.match(r"^(.*?)\s*\(([A-Za-z]{1,12})\)\s*$", str(label))   # "KEN PAXTON (REP)"
            name, feed_party = (m.group(1).strip(), m.group(2)) if m else (str(label).strip(), "")
            if NOT_VOTES.match(name):
                continue
            party = _party_tx(race, name, feed_party, candidates)
            split = {t: nums[k][i] for k, t in _HARRIS_TYPES.items()}
            total = nums["tv"][i]
            rest = total - sum(split.values())
            if rest < -0.5:
                raise RuntimeError(f"TX Harris: {race} {name}: vote types add to {sum(split.values()):,.0f}, "
                                   f"more than its total {total:,.0f}")
            if total > 10000 and rest > 0.05 * total:   # 2024: 0.1-0.4%
                notes.append(f"Harris: {race} {name}: {rest:,.0f} of {total:,.0f} votes not split by type")
            split["provisional"] = max(rest, 0.0)
            for t, v in split.items():
                rows.append(dict(state="TX", fips=fips, county="Harris County", race=race, party=party,
                                 candidate=name, vote_type=t, votes=v, ts=ts, complete=done))
    if not any(r["race"] == "SEN-TX" for r in rows):
        raise RuntimeError("TX Harris: no U.S. Senate rows in resultsbyballot.json (file layout changed?)")
    out = _fit_types(_sum(_frame(rows)))
    notes += [out.attrs["note"]] if out.attrs.get("note") else []
    out.attrs["source_time"] = str(d.get("dt") or "")
    if notes:
        out.attrs["note"] = "; ".join(notes)
    return out


_harris_last_time: dict[str, str] = {}   # code -> the newest file timestamp ("dt") seen


def harris(code, candidates=None, expect_date: str | None = ELECTION_DATE) -> pd.DataFrame:
    body = fetch(f"{HARRIS}/{code}/resultsbyballot.json", min_interval=MIN_INTERVAL, cache_name=f"TX_Harris_{code}.json")
    df = harris_json(body, candidates, expect_date, code=str(code))
    # an older file than one already read (a stale cache node) is refused; the county keeps
    # its last good rows and the feed shows as partial. ISO timestamps compare as strings.
    t, last = df.attrs.get("source_time", ""), _harris_last_time.get(str(code), "")
    if t and last and t < last:
        raise RuntimeError(f"TX Harris: got a file stamped {t}, older than {last} already read")
    if t:
        _harris_last_time[str(code)] = max(t, last)
    return df


def load_sources(path=SOURCES_FILE) -> dict:
    """data/live/tx_sources.json; see that file for the format."""
    if not path.exists():
        raise RuntimeError(f"{_rel(path)} not found: it maps each county to its Clarity id")
    cfg = json.loads(path.read_text())
    return {k: v for k, v in cfg.get("counties", cfg).items() if not k.startswith("_")}


def _source_key(spec: dict) -> str:
    return f"harris:{spec['harris']}" if spec.get("harris") else str(spec.get("clarity"))


def tx_counties(sources: dict | None = None, candidates=None, expect_date: str | None = ELECTION_DATE) -> pd.DataFrame:
    """Tidy TX frame from every configured county. A county without an id is left out
    quietly (expected until it posts one). A county that fails keeps its last good rows,
    if any, and is named in the frame's attrs["warning"] (the dashboard shows the feed as
    partial) and in `last_errors`. Raises only if no county could be read at all."""
    sources = load_sources() if sources is None else sources
    last_errors.clear()
    frames, failed, notes = [], [], []
    for county, spec in sources.items():
        try:
            if not spec:
                continue
            if not isinstance(spec, dict):
                raise RuntimeError(f"entry should be {{\"clarity\": <id>}}, got {spec!r}")
            if spec.get("skip"):
                continue
            if not (spec.get("clarity") or spec.get("harris")):
                last_errors[county] = "no 2026 id yet"
                continue
            src = _source_key(spec)
            df = (harris(spec["harris"], candidates, expect_date) if spec.get("harris")
                  else clarity_county(county, spec["clarity"], candidates, expect_date))
            _last_good[county] = (time.time(), src, df)
            frames.append(df)
            if df.attrs.get("note"):
                notes.append(df.attrs["note"])
        except Exception as e:  # noqa: BLE001 - one county must never break the rest
            msg = f"{type(e).__name__}: {e}"
            if county in _last_good and isinstance(spec, dict) and _last_good[county][1] == _source_key(spec):   # same election only
                t, _, df = _last_good[county]
                frames.append(df)
                msg += f" (keeping its file from {dt.datetime.fromtimestamp(t):%H:%M})"
            last_errors[county] = msg
            failed.append(county)
    if not frames:
        raise RuntimeError("no Texas county feed could be read: " + json.dumps(last_errors))
    out = pd.concat(frames, ignore_index=True)[COLS]
    warn = [f"county failing: {c}: {last_errors[c]}" for c in failed] + notes
    if warn:
        out.attrs["warning"] = "; ".join(warn)[:300]
    return out


def test_2024() -> pd.DataFrame:
    """Each county's 2024 presidential D/R totals against county_baseline("TX")."""
    df = tx_counties(SOURCES_2024, CANDIDATES_2024, expect_date="11/5/2024")
    df = df[df["race"] == "PRES-TX"]
    got = df[df["party"].isin(["D", "R"])].pivot_table(index=["fips", "county"], columns="party", values="votes",
                                                        aggfunc="sum").reset_index()
    b = county_baseline("TX").set_index("fips")[["pres2024_dem", "pres2024_gop"]]
    out = got.join(b, on="fips")
    out["d_diff"] = out["D"] - out["pres2024_dem"]
    out["r_diff"] = out["R"] - out["pres2024_gop"]
    return out


def _main(argv: list[str]) -> None:
    pd.set_option("display.width", 200)
    if argv and argv[0] == "test2024":
        print(test_2024().to_string(index=False))
    else:
        try:
            df = tx_counties()
            if not df.empty:
                print(df.groupby(["county", "race", "party"])["votes"].sum().unstack("party").to_string())
        except RuntimeError as e:
            print("error:", e)
    if last_errors:
        print("skipped:", json.dumps(last_errors, indent=1))


if __name__ == "__main__":
    _main(sys.argv[1:])
