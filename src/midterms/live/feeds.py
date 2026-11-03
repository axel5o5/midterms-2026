"""Election-night results adapters, one per results host.

Every adapter returns the same tidy frame:
    state, fips, county, race, party (D/R/O), candidate, vote_type, votes, ts
where race is "SEN-<ST>", a House key like "NC-07" (zero-padded, as in
house.py), "PRES-<ST>" (used for replays of 2024), or "GOV-<ST>".

Hosts (format and past election each adapter was checked against):
- NC  dl.ncsbe.gov S3 zip, precinct tab text with Election Day / Early /
      Absentee by Mail / Provisional columns. 2024-11-05 file; the 2026-11-03
      placeholder already lists US SENATE and the 14 House districts.
- GA  results.sos.ga.gov "Enhanced Voting" JSON, one request per county, vote
      groups per candidate. 2024NovGen. VA runs the same platform.
- IA, SC (and CO)  Clarity ENR detail.xml zip, vote types per county.
      IA 2024 general (EID 122322) and SC 2024 general (122436) match
      county_baseline exactly; 2026 general ids IA 127077, SC 127300 (see
      IA_EID_2026). Saved samples: data/reference/enr_samples/{IA,SC}/.
- MN  electionresultsfiles.sos.mn.gov allracesbycounty.txt (semicolon).
      2024-11-05.
- FL  flelectionfiles.floridados.gov ElecResultsFL.txt (county, no vote
      types). 2024-11-05; the 2026-11-03 placeholder exists.
- TX  2026: county Clarity sites (feeds_tx), because the state's new results host
      disallows AI crawlers. `tx()` reads the old host, results.texas-election.com
      County.json (county FIPS keys; early votes as EV), for the 2024 general (id
      49664); its election list stops at 2024.
- OH  liveresults.ohiosos.gov NIST 1500-100 XML. Only a zero-vote test file
      has been seen; the parser is untested on real counts. The host 429s
      after a few requests: poll it at most every 2-3 minutes.
- KS  county sites only, about 53% of the 2024 vote in the four biggest counties
      (46% without Shawnee, see below). The statewide host, ent.sos.ks.gov, sits
      behind a Cloudflare bot challenge (403, cf-mitigated: challenge), which we
      don't try to get past; its old mirror kssos.org/ent/ is disallowed by
      robots.txt and stale. Wyandotte (wycokck.org) returns 403. So, by county
      (robots.txt checked 2026-10-30; none disallows AI crawlers):
      Johnson   jocoelection.org: Electionware summary PDFs (TOTAL column only, no
                party labels) linked from the 2026 general event page, e.g.
                "GN2024 Unofficial Results Update 1.pdf"; 2024 general and 2026
                primary checked.
      Sedgwick  sedgwick.gov / sedgwickcounty.org (same site): Electionware summary
                PDFs under /media/<id>/ (ids rise with upload order) on a per-
                election page under /elections/election-results/; 2024 general
                1st..final..official and 2026 primary checked.
      Douglas   livevoterturnout.com ENR page (no robots.txt), county-wide contests
                with Absentee / Advanced / Election Day / Provisional columns.
                2026 general is index 22 (placeholder up since 2026-10-22); 2024
                general (18) and 2026 primary (21) checked. dgcoks.gov's archive
                page still links only up to 2024; apps.dgcoks.gov disallows
                AI crawlers and isn't used.
      Shawnee   every results file is on cdn.snco.gov, whose robots.txt is
                "User-agent: * / Disallow: /", so fetch() refuses it. The adapter
                still looks for a link on www.snco.gov and would read a report
                posted anywhere allowed, but expect Shawnee to be skipped.
      Party comes from candidate names (KS_CANDIDATES), so `ks()` takes the race
      regex and candidate names (point them at President / Harris / Trump to test
      on 2024: scripts/ks_2024_check.py). If discovery fails on the night, paste
      a report URL into data/live/ks_urls.json, e.g. {"Johnson": "https://..."};
      it is re-read on every call and wins over discovery. `KS_STATUS` says what
      each county did last.
No usable feed: MI, WI, AZ, NH, NJ, NY (state ENR); NE and ME only post
statewide or post-canvass files. PA has no 2026 Senate race; its 2026 general
is election id 117 (from electionreturns.pa.gov's election list).

Politeness: each file is checked at most once per `MIN_INTERVAL` seconds (15),
always as a conditional request (If-None-Match / If-Modified-Since), so an
unchanged file costs the host a header-only 304. NC's S3, FL and MN send ETags
(checked 2026-10-30); Clarity and Texas publish a small version file and the
big file's URL changes with it. Georgia's API caches for 60 s, so its county
files are fetched at most once a minute. Kansas county servers are asked at most
every 45 s per URL (KS_INTERVAL), the pages that only point at results every 10
minutes, and a failed request isn't retried sooner either. A changed body is kept under
data/raw-live/, and a host is refused if its robots.txt disallows the AI-crawler
user agents in CRAWLER_AGENTS.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from ..house import key as hkey
from ..snapshot import ROOT
from .baselines import county_baseline, norm_county, vote_type

RAW = ROOT / "data" / "raw-live"
MIN_INTERVAL = 15
UA = "Mozilla/5.0 (personal election-night research; conditional requests, each file at most every 15s)"
_s = requests.Session()
_s.headers["User-Agent"] = UA
_last: dict[str, tuple[float, bytes]] = {}
_validators: dict[str, dict[str, str]] = {}
changed_at: dict[str, float] = {}   # url -> time its body last changed
_robots: dict[str, bool] = {}
# AI-crawler user agents whose robots.txt rules this tool honours (a host that disallows any of
# them for a URL is not fetched)
CRAWLER_AGENTS = ("ClaudeBot", "anthropic-ai", "Claude-Web")
COLS = ["state", "fips", "county", "race", "party", "candidate", "vote_type", "votes", "ts", "complete"]


class Blocked(RuntimeError):
    pass


def _allowed(url: str) -> bool:
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in _robots:
        ok = True
        try:
            r = _s.get(host + "/robots.txt", timeout=15)
            if r.status_code == 200 and "user-agent" in r.text.lower():
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
                ok = all(rp.can_fetch(a, url) for a in CRAWLER_AGENTS)
        except requests.RequestException:
            pass
        _robots[host] = ok
    return _robots[host]


def fetch(url: str, *, min_interval: float = MIN_INTERVAL, cache_name: str | None = None) -> bytes:
    """Conditional GET with a per-URL rate limit, robots check, and a timestamped raw
    copy whenever the body changes."""
    if not _allowed(url):
        raise Blocked(f"robots.txt disallows AI crawlers for {url}")
    now = time.time()
    if url in _last and now - _last[url][0] < min_interval:
        return _last[url][1]
    headers = _validators.get(url, {}) if url in _last else {}
    r = _s.get(url, timeout=60, headers=headers)
    if r.status_code == 429:
        time.sleep(30)
        r = _s.get(url, timeout=60, headers=headers)
    if r.status_code == 304 and url in _last:
        _last[url] = (now, _last[url][1])
        return _last[url][1]
    r.raise_for_status()
    body = r.content
    v = {}
    if r.headers.get("ETag"):
        v["If-None-Match"] = r.headers["ETag"]
    if r.headers.get("Last-Modified"):
        v["If-Modified-Since"] = r.headers["Last-Modified"]
    _validators[url] = v
    if url not in _last or _last[url][1] != body:
        changed_at[url] = now
        host = urlparse(url).netloc.replace(":", "_")
        path = RAW / host / f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}_{cache_name or Path(urlparse(url).path).name or 'index'}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    _last[url] = (now, body)
    return body


def _fips_lookup(state: str) -> dict[str, str]:
    b = county_baseline(state)
    return dict(zip(b["key"], b["fips"]))


def _party(p: str) -> str:
    p = str(p).strip().upper()
    if p in ("DEM", "D", "DFL", "DEMOCRAT", "DEMOCRATIC") or p.startswith("DEM"):
        return "D"
    if p in ("REP", "R", "REPUBLICAN", "GOP") or p.startswith("REP"):
        return "R"
    return "O"


def _race(state: str, office: str) -> str | None:
    """Map an office name to a race key; None for offices we don't track."""
    o = re.sub(r"\s+", " ", office).strip().upper()
    if "PRESIDENT" in o:
        return f"PRES-{state}"
    if re.search(r"(U\.?\s?S\.?|UNITED STATES) SENAT", o):
        return f"SEN-{state}"
    m = re.search(r"(U\.?\s?S\.?|UNITED STATES) (HOUSE OF REPRESENTATIVES|REPRESENTATIVE|CONGRESS)\D*(\d+)", o)
    if m:
        return hkey(state, int(m.group(3)))
    if o.startswith("GOVERNOR"):
        return f"GOV-{state}"
    return None


def _rel(p: Path) -> Path:
    """A path as it reads from the repo root, for error messages."""
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return p


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLS)
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0)
    df["complete"] = df["complete"].fillna(False).astype(bool)   # county fully reported, per the feed
    return df


# ---- North Carolina ----------------------------------------------------------------

def nc(date: str = "2026-11-03") -> pd.DataFrame:
    d = pd.Timestamp(date)
    url = f"https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/{d:%Y_%m_%d}/results_pct_{d:%Y%m%d}.zip"
    z = zipfile.ZipFile(io.BytesIO(fetch(url)))
    t = pd.read_csv(z.open(z.namelist()[0]), sep="\t", dtype=str, keep_default_na=False)
    t.columns = [c.strip() for c in t.columns]
    t["race"] = t["Contest Name"].map(lambda o: _race("NC", o))
    t = t.dropna(subset=["race"])
    types = {"Election Day": "election_day", "Early Voting": "early", "Absentee by Mail": "mail", "Provisional": "provisional"}
    t["tv"] = pd.to_numeric(t["Total Votes"], errors="coerce").fillna(0)
    real = t[t["Real Precinct"].str.strip().eq("Y")] if "Real Precinct" in t else t
    pv = real.groupby(["County", "race", "Precinct"])["tv"].sum()
    done = (pv > 0).groupby(level=[0, 1]).all()
    long = t.melt(id_vars=["County", "race", "Choice", "Choice Party"], value_vars=list(types), var_name="vt", value_name="votes")
    long["votes"] = pd.to_numeric(long["votes"], errors="coerce").fillna(0)
    g = long.groupby(["County", "race", "Choice", "Choice Party", "vt"], as_index=False)["votes"].sum()
    fl = _fips_lookup("NC")
    ts = dt.datetime.now(dt.UTC)
    return _frame([dict(state="NC", fips=fl.get(norm_county(r.County)), county=r.County, race=r.race,
                        party=_party(r._4), candidate=r.Choice, vote_type=types[r.vt], votes=r.votes, ts=ts,
                        complete=bool(done.get((r.County, r.race), False)))
                   for r in g.itertuples()])


# ---- Georgia / Virginia (Enhanced Voting) ---------------------------------------------

def _ev_items(js: dict, state: str, county: str, fips: str | None, ts) -> list[dict]:
    rows = []
    for bi in js.get("ballotItems") or []:
        race = _race(state, bi["name"][0]["text"])
        if not race or not bi.get("summaryResults"):
            continue
        rs = bi.get("reportingStatus") or {}
        done = bool(rs.get("totalUnits")) and rs.get("reportingUnits") == rs.get("totalUnits")
        for opt in bi["summaryResults"].get("ballotOptions") or []:
            party = _party((opt.get("party") or {}).get("abbreviation", ""))
            name = opt["name"][0]["text"]
            groups = opt.get("groupResults") or []
            if groups:
                for gr in groups:
                    rows.append(dict(state=state, fips=fips, county=county, race=race, party=party, candidate=name,
                                     vote_type=vote_type(gr["groupName"][0]["text"]), votes=gr.get("voteCount", 0), ts=ts,
                                     complete=done))
            else:
                rows.append(dict(state=state, fips=fips, county=county, race=race, party=party, candidate=name,
                                 vote_type="total", votes=opt.get("voteCount", 0), ts=ts, complete=done))
    return rows


def enhanced_voting(state: str = "GA", election: str = "2026NovGen", *, host: str = "https://results.sos.ga.gov",
                    jurisdiction: str = "Georgia", counties: list[str] | None = None,
                    max_counties: int | None = None, pause: float = 0.5) -> pd.DataFrame:
    """County-by-county results. `counties` (shortNames like 'fulton-county-ga') limits
    the requests; `max_counties` fetches only the first N (for quick checks)."""
    base = f"{host}/results/public/api/elections"
    top = json.loads(fetch(f"{base}/{jurisdiction}/{election}/data", min_interval=60, cache_name=f"{state}_{election}.json"))
    kids = [c["shortName"] for c in (top.get("jurisdiction") or {}).get("childLocalities") or []]
    kids = counties or kids
    if max_counties:
        kids = kids[:max_counties]
    fl = _fips_lookup(state)
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for k in kids:
        try:
            js = json.loads(fetch(f"{base}/{k}/{election}/data", min_interval=60, cache_name=f"{k}_{election}.json"))
        except requests.HTTPError:
            continue
        name = js["jurisdiction"]["name"][0]["text"]
        rows += _ev_items(js, state, name, fl.get(norm_county(name)), ts)
        time.sleep(pause)
    return _frame(rows)


def ga(election: str = "2026NovGen", **kw) -> pd.DataFrame:
    return enhanced_voting("GA", election, **kw)


# ---- Clarity (IA, SC, CO) -----------------------------------------------------------

CLARITY_HOSTS = {"SC": "https://www.enr-scvotes.org", "default": "https://results.enr.clarityelections.com"}


def clarity_xml(state: str, xml_bytes: bytes) -> pd.DataFrame:
    root = ET.fromstring(xml_bytes)
    fl = _fips_lookup(state)
    pct = {c.get("name"): c.get("precinctsReportingPercent") for c in root.iter("County") if c.get("precinctsReportingPercent")}
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for c in root.iter("Contest"):
        race = _race(state, c.get("text", ""))
        if not race:
            continue
        for ch in c.iter("Choice"):
            party = _party(ch.get("party", ""))
            for vt in ch.iter("VoteType"):
                for co in vt.iter("County"):
                    rows.append(dict(state=state, fips=fl.get(norm_county(co.get("name"))), county=co.get("name"),
                                     race=race, party=party, candidate=ch.get("text"),
                                     vote_type=vote_type(vt.get("name")), votes=co.get("votes", 0), ts=ts,
                                     complete=str(pct.get(co.get("name"), "")).startswith("100")))
    return _frame(rows)


def clarity_check_date(state: str, eid: str | int, xml_bytes: bytes, expect_date: str) -> None:
    """Raise if the file's <ElectionDate> isn't `expect_date` (M/D/YYYY): a wrong or reused
    id must stop the feed loudly instead of feeding another election's votes."""
    root = ET.fromstring(xml_bytes)
    got, name = (root.findtext("ElectionDate") or "").strip(), (root.findtext("ElectionName") or "").strip()
    if not same_date(got, expect_date):
        raise RuntimeError(f"{state} Clarity election {eid} is {name!r} dated {got!r}, not {expect_date}: "
                           f"wrong id? set the right one in {_rel(FEED_IDS_FILE)}")


def same_date(a: str, b: str) -> bool:
    """'11/3/2026' == '11/03/2026' (Clarity's M/D/YYYY, with or without zero padding)."""
    def parse(s):
        try:
            return dt.datetime.strptime(s.strip().split()[0], "%m/%d/%Y").date()
        except (ValueError, IndexError):
            return None
    da = parse(a)
    return da is not None and da == parse(b)


def clarity(state: str, eid: str | int, expect_date: str | None = None) -> pd.DataFrame:
    host = CLARITY_HOSTS.get(state, CLARITY_HOSTS["default"])
    ver = fetch(f"{host}/{state}/{eid}/current_ver.txt").decode().strip()
    z = zipfile.ZipFile(io.BytesIO(fetch(f"{host}/{state}/{eid}/{ver}/reports/detailxml.zip", cache_name=f"{state}_{eid}_detailxml.zip")))
    xml = z.read("detail.xml")
    if expect_date:
        clarity_check_date(state, eid, xml, expect_date)
    df = clarity_xml(state, xml)
    if expect_date and not (df["race"] == f"SEN-{state}").any():
        # the right election but no Senate rows: Clarity changed the file's layout
        raise RuntimeError(f"{state} Clarity election {eid}: no U.S. Senate rows by county in detail.xml "
                           "(file layout changed?)")
    return df


# ---- Minnesota ----------------------------------------------------------------------

def mn(date: str = "2026-11-03") -> pd.DataFrame:
    d = pd.Timestamp(date)
    raw = fetch(f"https://electionresultsfiles.sos.mn.gov/{d:%Y%m%d}/allracesbycounty.txt")
    try:
        body = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # the 2026 file has Latin-1 accents
        body = raw.decode("latin-1")
    t = pd.read_csv(io.StringIO(body), sep=";", header=None, dtype=str)
    t = t.rename(columns={1: "cc", 4: "office", 7: "cand", 10: "party", 11: "prep", 12: "ptot", 13: "votes"})
    t["race"] = t["office"].map(lambda o: _race("MN", o))
    t = t.dropna(subset=["race"])
    t = t[t["cc"].notna() & (t["cc"].str.strip() != "")]
    t["fips"] = "27" + (2 * t["cc"].astype(int) - 1).astype(str).str.zfill(3)  # MN county codes are alphabetical
    names = county_baseline("MN").set_index("fips")["county"]
    ts = dt.datetime.now(dt.UTC)
    return _frame([dict(state="MN", fips=r.fips, county=names.get(r.fips), race=r.race, party=_party(r.party),
                        candidate=r.cand, vote_type="total", votes=r.votes, ts=ts,
                        complete=str(r.prep).strip() == str(r.ptot).strip() and str(r.ptot).strip() not in ("", "0"))
                   for r in t.itertuples()])


# ---- Florida ------------------------------------------------------------------------

def fl(date: str = "2026-11-03") -> pd.DataFrame:
    d = pd.Timestamp(date)
    body = fetch(f"https://flelectionfiles.floridados.gov/enightfilespublic/{d:%Y%m%d}_ElecResultsFL.txt").decode("latin-1")
    t = pd.read_csv(io.StringIO(body), sep="\t", dtype=str, keep_default_na=False)
    t.columns = [c.strip() for c in t.columns]
    office = t["RaceName"] + " " + t["Juris1num"].str.strip()
    t["race"] = [(_race("FL", o) if not rn.upper().startswith("REPRESENTATIVE IN CONGRESS")
                  else hkey("FL", int(j)) if j.strip().isdigit() else None)
                 for o, rn, j in zip(office, t["RaceName"], t["Juris1num"])]
    t = t.dropna(subset=["race"])
    fl_ = _fips_lookup("FL")
    ts = dt.datetime.now(dt.UTC)
    return _frame([dict(state="FL", fips=fl_.get(norm_county(r.CountyName)), county=r.CountyName, race=r.race,
                        party=_party(r.PartyCode), candidate=f"{r.CanNameFirst} {r.CanNameLast}", vote_type="total",
                        votes=r.CanVotes, ts=ts,
                        complete=r.PrecinctsReporting.strip() == r.Precincts.strip() and r.Precincts.strip() not in ("", "0"))
                   for r in t.itertuples()])


# ---- Texas --------------------------------------------------------------------------

def tx(election_id: int | str, version: int | str | None = None) -> pd.DataFrame:
    base = f"https://results.texas-election.com/static/data/election/{election_id}"
    if version is None:
        version = json.loads(fetch(f"{base}/Version.json", cache_name=f"tx_{election_id}_version.json"))["___versionNo"]
    d = json.loads(fetch(f"{base}/{version}/County.json", cache_name=f"tx_{election_id}_county.json"))
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for fips, c in d.items():
        for race_ in (c.get("Races") or {}).values():
            race = _race("TX", race_.get("ON", ""))
            if not race:
                continue
            for cand in (race_.get("C") or {}).values():
                ev = cand.get("EV") or 0
                rows.append(dict(state="TX", fips=str(fips).zfill(5), county=c.get("N"), race=race, party=_party(cand.get("P")),
                                 candidate=cand.get("N"), vote_type="early", votes=ev, ts=ts))
                rows.append(dict(state="TX", fips=str(fips).zfill(5), county=c.get("N"), race=race, party=_party(cand.get("P")),
                                 candidate=cand.get("N"), vote_type="election_day", votes=(cand.get("V") or 0) - ev, ts=ts))
    return _frame(rows)


# ---- Ohio (NIST 1500-100) -------------------------------------------------------------

def oh(url: str = "https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob") -> pd.DataFrame:
    """Untested on real counts (only a zero-vote test file has been seen)."""
    root = ET.fromstring(fetch(url, min_interval=150, cache_name="ohio_vssc.xml"))
    ns = {"n": root.tag.split("}")[0].strip("{")}
    units = {u.get("ObjectId"): u.get("Name") for u in root.iter(f"{{{ns['n']}}}GpUnit") if u.get("Type") == "County"}
    unit_done = {u.get("Name"): (u.get("SubUnitsReported") == u.get("TotalSubUnits") and u.get("TotalSubUnits") not in (None, "0"))
                 for u in root.iter(f"{{{ns['n']}}}GpUnit") if u.get("Type") == "County"}
    parties = {p.get("ObjectId"): (p.findtext("n:Abbreviation", default="", namespaces=ns) or p.findtext("n:Name/n:Text", default="", namespaces=ns))
               for p in root.iter(f"{{{ns['n']}}}Party")}
    cands = {c.get("ObjectId"): (c.findtext("n:BallotName/n:Text", default="", namespaces=ns), parties.get(c.findtext("n:PartyId", default="", namespaces=ns), ""))
             for c in root.iter(f"{{{ns['n']}}}Candidate")}
    fl_ = _fips_lookup("OH")
    ts = dt.datetime.now(dt.UTC)
    rows = []
    for contest in root.iter(f"{{{ns['n']}}}Contest"):
        race = _race("OH", contest.get("Name", ""))
        if not race:
            continue
        for sel in contest.iter(f"{{{ns['n']}}}BallotSelection"):
            cid = (sel.findtext("n:CandidateIds", default="", namespaces=ns) or "").split()
            name, party = cands.get(cid[0], ("", "")) if cid else ("", "")
            for vc in sel.iter(f"{{{ns['n']}}}VoteCounts"):
                unit = units.get(vc.findtext("n:GpUnitId", default="", namespaces=ns))
                if not unit:
                    continue
                rows.append(dict(state="OH", fips=fl_.get(norm_county(unit)), county=unit, race=race, party=_party(party),
                                 candidate=name, vote_type=vote_type(vc.findtext("n:Type", default="total", namespaces=ns)),
                                 votes=vc.findtext("n:Count", default="0", namespaces=ns), ts=ts,
                                 complete=unit_done.get(unit, False)))
    return _frame(rows)


# ---- Kansas (four county sites) ------------------------------------------------------
#
# Kansas's statewide host is unusable (see the module docstring), so KS is the four
# biggest counties' own sites: Johnson and Sedgwick post Electionware summary PDFs,
# Douglas runs a livevoterturnout.com results page, Shawnee's files sit on a host whose
# robots.txt disallows everyone. Party labels aren't in the PDFs, so candidates are
# matched by name (KS_CANDIDATES); everyone unmatched is "O".

KS_URLS_FILE = ROOT / "data" / "live" / "ks_urls.json"   # optional {"Johnson": "<url>", ...} override
KS_INTERVAL = 45   # seconds between requests for any one county URL (county servers)
KS_INDEX_INTERVAL = 600   # pages that only point at the results page (Sedgwick index, Douglas archive)
KS_RACE = r"\b(?:U\.?\s?S\.?|UNITED STATES)\s+SENAT"
KS_CANDIDATES: dict[str, tuple[str, ...]] = {"D": ("Hamilton",), "R": ("Marshall",)}
KS_DOUGLAS_2026 = "https://www.livevoterturnout.com/ENR/douglasksenr/22/en/Index_22.html"   # placeholder seen 2026-10-30
KS_PAGES = {   # pages that link the county's newest report, checked in order
    "Johnson": ["https://www.jocoelection.org/events-elections/november-3-2026-general-election",
                "https://www.jocoelection.org/"],
    "Sedgwick": ["https://www.sedgwick.gov/elections/election-results/2026-general-election/"],
    "Shawnee": ["https://www.snco.gov/election/", "https://www.snco.gov/election/results.php"],
    "Douglas": ["https://www.dgcoks.gov/county-clerk/voting-and-elections/results-and-archive"],
}
KS_SEDGWICK_INDEX = "https://www.sedgwick.gov/elections/election-results/"
KS_STATUS: dict[str, str] = {}   # county -> what the last ks() call did (url used, or why nothing)
_ks_last_url: dict[str, str] = {}
_ks_parsed: dict[tuple, tuple[list[dict], bool]] = {}
_ks_fail: dict[str, tuple[float, Exception]] = {}
_KS_EXCLUDE = re.compile(r"primary|\bpr ?20\d\d|precinct|\bpct|write|kids|committee|canvass|audit|notice|recount|"
                         r"certif|township|judicial|sovc|statement of votes|turnout|\.csv|\.xlsx?\b|sample")


def _ks_fetch(url: str, interval: float = KS_INTERVAL, **kw) -> bytes:
    """fetch(), but a failure (404 before a page exists, timeout) is also remembered for
    `interval` seconds, so the engine's every-few-seconds calls don't retry it."""
    f = _ks_fail.get(url)
    if f and time.time() - f[0] < interval:
        raise f[1]
    try:
        body = fetch(url, min_interval=interval, **kw)
    except Exception as e:
        _ks_fail[url] = (time.time(), e)
        raise
    _ks_fail.pop(url, None)
    return body


def _ks_links(body: bytes, base: str) -> list[tuple[str, str]]:
    """(absolute url, 'link text + decoded url') for every <a href> on a page."""
    from html import unescape
    from urllib.parse import unquote, urljoin
    t = body.decode("utf-8", "replace")
    out = []
    for href, inner in re.findall(r'(?is)<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', t):
        url = urljoin(base, unescape(href.strip()))
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        out.append((url, f"{text} {unquote(url)}"))
    return out


def ks_rank(label: str) -> tuple[int, int, int]:
    """Order reports newest-last by their link text / file name:
    advance < update N (or 'Nth') < election-night final < Wed/Thu/Fri updates < official."""
    from urllib.parse import unquote
    s = unquote(label).lower()
    if re.search(r"(?<!un)offic(?:i?al|ail)", s):   # 'Offical', 'Officail' both seen
        return (5, 0, 0)
    day = re.search(r"\b(wed|thu|fri|mon)[a-z]*\b", s)
    if day:
        return (4, ["wed", "thu", "fri", "mon"].index(day.group(1)), int(bool(re.search(r"afternoon|evening|\bpm\b", s))))
    if "final" in s:
        return (3, 0, 0)
    m = re.search(r"update[\s_-]*(\d+)", s) or re.search(r"\b(\d+)(?:st|nd|rd|th)\b", s)
    if m:
        return (2, int(m.group(1)), 0)
    if "advance" in s:
        return (1, 0, 0)
    return (0, 0, 0)


def _ks_pick(links: list[tuple[str, str]], *, need: str | None = None, kinds=(".pdf",)) -> tuple[str, str] | None:
    """Newest results report among `links`: a results file (by extension) whose label mentions
    results, matches `need` (e.g. 2026 + general) and none of the side reports."""
    cands = []
    for pos, (url, label) in enumerate(links):
        low = label.lower()
        if (not urlparse(url).path.lower().endswith(kinds) or not re.search(r"result|official|unoffic|final", low)
                or _KS_EXCLUDE.search(low)):
            continue
        if need and not re.search(need, low):
            continue
        media = re.search(r"/media/(\d+)/", url)   # Sedgwick's media ids rise with upload order
        cands.append((ks_rank(label), int(media.group(1)) if media else 0, -pos, url, label))
    if not cands:
        return None
    best = max(cands)
    return best[3], best[4]


def _ks_overrides() -> dict[str, str]:
    try:
        d = json.loads(KS_URLS_FILE.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        KS_STATUS["ks_urls.json"] = f"ignored, unreadable: {e!r}"
        return {}
    return {str(k).strip().title(): str(v).strip() for k, v in d.items() if isinstance(v, str) and v.strip()}


def _ks_discover(county: str) -> tuple[str, str] | None:
    """(url, label) of the county's newest 2026 general report, or None if nothing is posted."""
    need_2026_general = r"(?=.*2026)(?=.*(general|\bgn))"
    if county == "Douglas":
        for page in KS_PAGES["Douglas"]:
            links = _ks_links(_ks_fetch(page, KS_INDEX_INTERVAL), page)
            for url, label in links:
                if "livevoterturnout.com" in url and re.search(need_2026_general, label.lower()):
                    return url, label
        return KS_DOUGLAS_2026, "Douglas 2026 general ENR (known url)"
    pages = list(KS_PAGES[county])
    need = need_2026_general
    if county == "Sedgwick":
        # one sub-page per election, linked from the index; its files carry no year
        idx = _ks_links(_ks_fetch(KS_SEDGWICK_INDEX, KS_INDEX_INTERVAL), KS_SEDGWICK_INDEX)
        subs = [u for u, lab in idx if "/election-results/" in u and re.search(need_2026_general, u.lower())]
        pages = list(dict.fromkeys(subs + pages))
        need = None
    kinds = (".pdf", ".htm", ".html") if county == "Shawnee" else (".pdf",)
    for page in pages:
        try:
            body = _ks_fetch(page)
        except requests.HTTPError as e:   # Sedgwick's sub-page 404s until it's created
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        # on the general-election page itself every file is the 2026 general
        page_need = None if county == "Johnson" and "2026-general" in page else need
        hit = _ks_pick(_ks_links(body, page), need=page_need, kinds=kinds)
        if hit:
            return hit
    return None


def _pdf_text(pdf: bytes) -> str:
    """Text of a downloaded PDF via poppler's pdftotext -layout. The file is untrusted:
    it's only handed to pdftotext as data, in a fresh temp directory."""
    import subprocess
    import tempfile
    if not pdf.startswith(b"%PDF"):
        raise ValueError("not a PDF (got %r...)" % pdf[:40])
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "report.pdf"
        p.write_bytes(pdf)
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {r.stderr.decode(errors='replace')[:200]}")
    return r.stdout.decode("utf-8", "replace")


def _ks_party(name: str, candidates: dict[str, tuple[str, ...]], feed_party: str | None = None) -> str:
    for party, names in candidates.items():
        if any(re.search(rf"\b{re.escape(n)}\b", name, re.I) for n in names):
            return party
    return _party(feed_party) if feed_party else "O"


_EW_LINE = re.compile(r"^(\S.*?)\s{2,}([\d,]+)(?:\s+[\d.]+%)?\s*$")
_EW_SKIP = re.compile(r"^(total votes|contest totals?|overvotes|undervotes|blank|not assigned|precincts|registered|"
                      r"ballots cast|voter turnout|times (cast|counted))", re.I)


def electionware_summary(text: str, race_pattern: str = KS_RACE) -> tuple[list[tuple[str, int]], bool]:
    """Candidate totals for the contests matching `race_pattern` in an Electionware
    'Summary Results' report (pdftotext -layout), and whether the report is complete.

    Contest headers are the line before 'Vote For N'. Candidate lines start at column 0
    and end in a count; indented lines (write-in breakdowns, over/undervotes, the race's
    'Precincts Reporting') are not candidates. Complete = the header says Final/Official,
    or every Election Day precinct is in."""
    lines = text.splitlines()
    heads = []
    for i, line in enumerate(lines):
        if re.match(r"\s*Vote For\s+\d+", line, re.I):
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            heads.append((j, lines[j].strip() if j >= 0 else ""))
    got: dict[tuple[str, str], int] = {}
    race_status = []
    for k, (j, contest) in enumerate(heads):
        if not re.search(race_pattern, contest, re.I):
            continue
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        for line in lines[j + 1:end]:
            m = re.match(r"\s*Precincts Reporting\s+([\d,]+)\s+of\s+([\d,]+)", line, re.I)
            if m:
                race_status.append((int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))))
            if not line[:1].strip():
                continue
            m = _EW_LINE.match(line)
            if not m or _EW_SKIP.match(m.group(1)):
                continue
            name = m.group(1).strip()
            if re.match(r"write[- ]?in", name, re.I):
                name = "Write-in"
            got.setdefault((contest, name), int(m.group(2).replace(",", "")))
    head = " ".join(lines[:4]).upper()
    final = bool(re.search(r"\bFINAL\b", head) or re.search(r"(?<!UN)OFFIC(?:I?AL|AIL)", head))
    ed = re.search(r"Election Day Precincts Reporting\s+([\d,]+)\s+of\s+([\d,]+)", text, re.I)
    ed_done = bool(ed) and ed.group(1) == ed.group(2) and ed.group(2) != "0"
    race_done = bool(race_status) and all(a == b > 0 for a, b in race_status)
    rows: dict[str, int] = {}
    for (_, name), v in got.items():
        rows[name] = rows.get(name, 0) + v
    return list(rows.items()), final or ed_done or race_done


def livevoterturnout_summary(page: str, race_pattern: str = KS_RACE) -> tuple[list[tuple[str, str | None, str, int]], bool]:
    """(candidate, party label, vote type label, votes) for contests matching `race_pattern`
    on a livevoterturnout.com ENR page, and whether every precinct is fully reporting.

    The county-wide contest list holds, per contest, an inline array
    [['name', absentee, advanced, election day, provisional, total], ...] (read here as
    text, never run) whose columns are the contest's DetailTitle cells."""
    from html import unescape
    i = page.find('id="contestListLayer"')
    rows: list[tuple[str, str | None, str, int]] = []
    if i >= 0:
        for block in re.split(r'<div id="listid_\d+"[^>]*class="list-item">', page[i:])[1:]:
            m = re.search(r'aria-label="Contest: ([^"]*)"', block)
            if not m or not re.search(race_pattern, unescape(m.group(1)), re.I):
                continue
            labels = [re.sub(r"\s+", " ", unescape(x)).strip()
                      for x in re.findall(r'data-candidate="true"[^>]*>\s*<span[^>]*>([^<]*)</span>', block)]
            party_of = {}
            for lab in labels:
                pm = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", lab)
                party_of[pm.group(1) if pm else lab] = pm.group(2) if pm else None
            titles = [unescape(x).strip() for x in re.findall(r'class="DetailTitle"\s*>([^<]*)<', block, re.I)]
            arr = re.search(r"\[\[(.*?)\]\]", block, re.S)
            parsed = []
            if arr:
                for em in re.finditer(r"\[\s*(['\"])((?:\\.|(?!\1).)*)\1\s*,([^\[\]]*)\]", "[" + arr.group(1) + "]"):
                    name = em.group(2).replace("\\'", "'").replace('\\"', '"')
                    nums = [int(float(x)) for x in em.group(3).split(",") if x.strip()]
                    parsed.append((name, nums))
            if not parsed:   # fall back to the visible table's totals
                votes = re.findall(r'data-votes="true"[^>]*>\s*([\d,]+)\s*<', block)
                parsed = [(re.sub(r"\s*\([^()]*\)\s*$", "", lab), [int(v.replace(",", ""))]) for lab, v in zip(labels, votes)]
            for name, nums in parsed:
                party = next((p for n, p in party_of.items() if n == name or n.startswith(name)), None)
                split = (len(titles) == len(nums) and titles[-1].strip().upper() == "TOTAL"
                         and sum(nums[:-1]) == nums[-1] and len(nums) > 1)
                if split:
                    rows += [(name, party, t, v) for t, v in zip(titles[:-1], nums[:-1])]
                elif nums:
                    rows.append((name, party, "total", nums[-1]))

    def count(label: str) -> int | None:
        m = re.search(label + r"</span>\s*</div>\s*<div[^>]*>\s*<span>([\d,]+)</span>", page)
        return int(m.group(1).replace(",", "")) if m else None
    not_rep, part, full = count("Not Reporting"), count("Partially Reporting"), count("Fully Reporting")
    complete = not_rep == 0 and not part and bool(full)
    return rows, complete


def _ks_vote_type(label: str) -> str:
    """'Absentee Ballots' -> mail, 'Advanced Voting' -> early, 'Election Day' -> election_day."""
    if label == "total":
        return "total"
    return vote_type(re.sub(r"\s+(BALLOTS?|VOTES?)$", "", label.strip().upper()))


def _ks_parse(county: str, body: bytes, label: str, race_pattern: str) -> tuple[list[dict], bool]:
    """Cached on the body, since the engine calls adapters every few seconds."""
    import hashlib
    key = (county, hashlib.sha1(body).hexdigest(), race_pattern)
    if key not in _ks_parsed:
        if body.startswith(b"%PDF"):
            cands, complete = electionware_summary(_pdf_text(body), race_pattern)
            out = [dict(candidate=n, party_label=None, vote_type="total", votes=v) for n, v in cands]
        else:
            page = body.decode("utf-8", "replace")
            if 'id="contestListLayer"' in page or "livevoterturnout" in page.lower() or "Election Night Results" in page:
                rows, complete = livevoterturnout_summary(page, race_pattern)
                out = [dict(candidate=n, party_label=p, vote_type=_ks_vote_type(t), votes=v) for n, p, t, v in rows]
            else:   # an HTML report (Shawnee's old format): read its text like a summary report
                from html import unescape
                text = unescape(re.sub(r"(?s)<(script|style).*?</\1>|<[^>]+>", "\n", page))
                cands, complete = electionware_summary(text, race_pattern)
                out = [dict(candidate=n, party_label=None, vote_type="total", votes=v) for n, v in cands]
        if ks_rank(label)[0] >= 3:   # election-night final, later updates, official
            complete = True
        _ks_parsed[key] = (out, complete)
    return _ks_parsed[key]


def ks_county(county: str, url: str | None = None, *, label: str | None = None, race_pattern: str = KS_RACE,
              candidates: dict[str, tuple[str, ...]] | None = None, race: str = "SEN-KS") -> pd.DataFrame:
    """One county's newest report as the tidy frame. `url` skips discovery (2024 tests,
    or a pasted override); empty frame if the county hasn't posted yet."""
    candidates = KS_CANDIDATES if candidates is None else candidates
    if url is None:
        hit = _ks_discover(county)
        if hit is None:
            if county in _ks_last_url:   # discovery page hiccup: keep using the last report found
                url, label = _ks_last_url[county], _ks_last_url[county]
            else:
                KS_STATUS[county] = "not posted yet"
                return _frame([])
        else:
            url, label = hit
            _ks_last_url[county] = url
    body = _ks_fetch(url, cache_name=f"ks_{county.lower()}_{Path(urlparse(url).path).name or 'index'}")
    out, complete = _ks_parse(county, body, label or url, race_pattern)
    fips = _fips_lookup("KS").get(norm_county(county))
    ts = dt.datetime.now(dt.UTC)
    KS_STATUS[county] = f"{len(out)} rows{' (complete)' if complete else ''} from {url}"
    return _frame([dict(state="KS", fips=fips, county=f"{county} County", race=race,
                        party=_ks_party(r["candidate"], candidates, r["party_label"]), candidate=r["candidate"],
                        vote_type=r["vote_type"], votes=r["votes"], ts=ts, complete=complete) for r in out])


def ks(race_pattern: str = KS_RACE, candidates: dict[str, tuple[str, ...]] | None = None, race: str = "SEN-KS",
       urls: dict[str, str] | None = None) -> pd.DataFrame:
    """Kansas from its four biggest counties (52.6% of the 2024 vote). `urls` (or
    data/live/ks_urls.json) pins a county's report URL; other counties are discovered.
    A county that fails or hasn't posted is skipped (see KS_STATUS); raises only if
    every county errored."""
    pinned = {**_ks_overrides(), **{k.title(): v for k, v in (urls or {}).items()}}
    frames, errors = [], []
    for county in KS_PAGES:
        try:
            frames.append(ks_county(county, pinned.get(county), label=pinned.get(county),
                                    race_pattern=race_pattern, candidates=candidates, race=race))
        except Blocked as e:
            KS_STATUS[county] = f"skipped: {e}"
            errors.append(county)
        except Exception as e:   # one county's failure mustn't stop the others
            KS_STATUS[county] = f"error: {e!r}"[:300]
            errors.append(county)
    if len(errors) == len(KS_PAGES):
        raise RuntimeError("every Kansas county failed: " + "; ".join(f"{c}: {KS_STATUS[c]}" for c in errors))
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else _frame([])


# 2026 general-election ids, each live with zero votes and election date 11/3/2026 when checked:
# IA  127077  results.enr.clarityelections.com/IA/elections.json lists "2026 General Election" (2026-11-02)
# SC  127300  scvotes.gov's home page links it as "View Results for the 2026 Statewide General
#             Election" (2026-11-02)
# On the night, an id in data/live/feed_ids.json (e.g. {"IA": "127077"}) wins over these, so a
# changed id needs no code edit; it is re-read on every call.
IA_EID_2026: str | None = "127077"
SC_EID_2026: str | None = "127300"
ELECTION_DATE_2026 = "11/3/2026"
FEED_IDS_FILE = ROOT / "data" / "live" / "feed_ids.json"


def feed_id(state: str, default) -> str:
    """The state's 2026 election id: data/live/feed_ids.json if it names one, else `default`.
    Raises if neither is set, so the dashboard shows the feed as broken instead of quiet."""
    try:
        override = json.loads(FEED_IDS_FILE.read_text()).get(state)
    except FileNotFoundError:
        override = None
    except (OSError, ValueError, AttributeError) as e:
        raise RuntimeError(f"{_rel(FEED_IDS_FILE)} is unreadable: {e!r}") from e
    eid = str(override).strip() if override not in (None, "") else default
    if eid in (None, ""):
        raise RuntimeError(f"{state} 2026 election id not set: put it in {_rel(FEED_IDS_FILE)}")
    return str(eid)


ADAPTERS = {
    "NC": lambda: nc(), "GA": lambda: ga(),
    "IA": lambda: clarity("IA", feed_id("IA", IA_EID_2026), expect_date=ELECTION_DATE_2026),
    "SC": lambda: clarity("SC", feed_id("SC", SC_EID_2026), expect_date=ELECTION_DATE_2026),
    "MN": lambda: mn(), "FL": lambda: fl(),
    # Texas's 2026 statewide host blocks AI crawlers (see feeds_tx), so TX is its Clarity counties
    "TX": lambda: __import__("midterms.live.feeds_tx", fromlist=["tx_counties"]).tx_counties(),
    "OH": lambda: oh(), "KS": lambda: ks(),
    "NE": lambda: __import__("midterms.live.feeds_ne", fromlist=["ne"]).ne(),
    "MI": lambda: __import__("midterms.live.feeds_mi", fromlist=["mi"]).mi(),
}
