"""County baselines for election night.

Files in data/reference/ (built once by `build_reference()` from the research
downloads; licences noted):
- county_baseline_2024.csv: 2024 and 2020 presidential votes by county
  (tonmcg/US_County_Level_Election_Results_08-24, MIT; compiled from news
  outlets, not official) + 2024 EAC EAVS registration and ballots by mode
  (public domain).
- county_2022_by_mode.csv: 2022 Senate (or governor where no Senate race)
  votes by county, party and vote type (MEDSL 2022 precinct returns, CC0).

Vote types are normalised to: election_day, early (in-person early / one-stop /
advance), mail (absentee / by mail), provisional, total (no breakdown).
Margins are D minus R as points of all votes in the unit.
"""

from __future__ import annotations

import os
import re
import shutil
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..snapshot import ROOT

REF = ROOT / "data" / "reference"
# Raw inputs for build_reference() (the MEDSL 2022 precinct files and the compiled county
# baseline), only needed to rebuild data/reference/; point MIDTERMS_RESEARCH at them.
RESEARCH = Path(os.environ.get("MIDTERMS_RESEARCH", ROOT / "data" / "research"))

VOTE_TYPES = {
    "ELECTION DAY": "election_day", "ELECTION DAY VOTES": "election_day",
    "ONE STOP": "early", "EARLY VOTING": "early", "EARLY": "early", "ADVANCED": "early",
    "ADVANCE VOTING": "early", "ADVANCED VOTING": "early", "ADVANCE IN PERSON": "early",
    "ABSENTEE BY MAIL": "mail", "ABSENTEE": "mail", "MAIL": "mail", "MAIL VOTES": "mail", "MAIL-IN": "mail",
    "PROVISIONAL": "provisional", "PROVISIONAL VOTES": "provisional", "FAILSAFE": "provisional",
    "PROVIONSAL": "provisional",   # sic, in SC's 2026 file
    "FAILSAFE PROVISIONAL": "provisional", "LATE VOTES": "provisional",
    "TOTAL": "total",
}

STATE_FIPS = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
              "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20",
              "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
              "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
              "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
              "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
              "WI": "55", "WY": "56"}


def vote_type(label: str) -> str:
    s = re.sub(r"\s+", " ", str(label)).strip().upper()
    return VOTE_TYPES.get(s, "other")


def norm_county(name: str) -> str:
    """'St. Lucie County' / 'ST LUCIE' / 'DeKalb' -> 'STLUCIE' / 'DEKALB' for joining."""
    s = str(name).upper()
    s = re.sub(r"\b(COUNTY|PARISH|BOROUGH|CENSUS AREA|CITY AND BOROUGH|MUNICIPALITY)\b", "", s)
    s = s.replace("SAINT", "ST")
    return re.sub(r"[^A-Z]", "", s)


def build_reference(research: Path = RESEARCH) -> None:
    REF.mkdir(parents=True, exist_ok=True)
    shutil.copy(research / "county_baseline.csv", REF / "county_baseline_2024.csv")
    s = pd.read_csv(research / "medsl_2022_senate_precinct/senate2022_county_party_mode.csv", dtype={"county_fips": str})
    g = pd.read_csv(research / "medsl_2022_state_precinct/gov2022_county_party_mode.csv", dtype={"county_fips": str})
    s["office"], g["office"] = "senate", "governor"
    g = g[~g["state"].isin(set(s["state"]))]          # governor only where there was no Senate race
    d = pd.concat([s, g], ignore_index=True)
    d = d[d["special"].fillna(False).astype(str).str.upper().isin(["FALSE", "0", "NAN"]) | d["special"].isna()]
    d = d.dropna(subset=["county_fips"])
    d["county_fips"] = d["county_fips"].str.zfill(5)
    d["vote_type"] = d["mode"].map(vote_type)
    # where a county has a breakdown, drop its TOTAL rows (GA, SC carry both)
    has_split = d[d["vote_type"] != "total"].groupby("county_fips").size()
    d = d[~((d["vote_type"] == "total") & d["county_fips"].isin(has_split.index))]
    d["party"] = d["party"].fillna("").str.upper().map(lambda p: "D" if p == "DEMOCRAT" else ("R" if p == "REPUBLICAN" else "O"))
    out = d.pivot_table(index=["state", "county_fips", "office", "vote_type"], columns="party", values="votes",
                        aggfunc="sum", fill_value=0).reset_index()
    for c in ("D", "R", "O"):
        if c not in out:
            out[c] = 0
    out["total"] = out[["D", "R", "O"]].sum(axis=1)
    out.rename(columns={"county_fips": "fips", "D": "dem", "R": "rep", "O": "oth"}).to_csv(REF / "county_2022_by_mode.csv", index=False)


@lru_cache(maxsize=1)
def _baseline_file() -> pd.DataFrame:
    return pd.read_csv(REF / "county_baseline_2024.csv", dtype={"county_fips": str})


@lru_cache(maxsize=1)
def _midterm_file() -> pd.DataFrame:
    return pd.read_csv(REF / "county_2022_by_mode.csv", dtype={"fips": str})


def county_baseline(state: str | None = None) -> pd.DataFrame:
    """One row per county: fips, state, county, 2024/2020 presidential margins and totals."""
    b = _baseline_file().copy()
    b = b.rename(columns={"county_fips": "fips"})
    b["st"] = b["fips"].str[:2].map({v: k for k, v in STATE_FIPS.items()})
    b["margin24"] = 100 * (b["pres2024_dem"] - b["pres2024_gop"]) / b["pres2024_total"]
    b["margin20"] = 100 * (b["pres2020_dem"] - b["pres2020_gop"]) / b["pres2020_total"]
    b["key"] = b["county"].map(norm_county)
    return b[b["st"] == state].reset_index(drop=True) if state else b


def midterm_2022(state: str) -> pd.DataFrame:
    """2022 Senate/governor votes by county and vote type for one state."""
    d = _midterm_file()
    return d[d["state"] == state].reset_index(drop=True)


def expected_vote(state: str, pace: float = 1.0) -> pd.DataFrame:
    """Expected 2026 votes per county and vote type, and each vote type's lean.

    expected = 2022 votes x `pace` (statewide turnout relative to 2022; the
    projection also learns it from counties that finish). lean = that vote
    type's 2022 margin minus the county's 2022 margin, i.e. how much more
    Democratic its mail (say) ran than the county as a whole. Counties without
    a 2022 breakdown get one 'total' row with lean 0.
    """
    m = midterm_2022(state)
    if m.empty:  # no 2022 statewide race in MEDSL (e.g. MI): fall back to 2024 presidential totals x 0.75
        b = county_baseline(state)
        out = pd.DataFrame({"fips": b["fips"], "vote_type": "total", "expected": 0.75 * pace * b["pres2024_total"],
                            "lean": 0.0, "share": 1.0})
        return _measured_leans(state, out)
    tot = m.groupby("fips")[["dem", "rep", "total"]].sum()
    county_margin = 100 * (tot["dem"] - tot["rep"]) / tot["total"].where(tot["total"] > 0)
    m = m.assign(expected=pace * m["total"],
                 lean=100 * (m["dem"] - m["rep"]) / m["total"].where(m["total"] > 0) - m["fips"].map(county_margin),
                 share=m["total"] / m["fips"].map(tot["total"]))
    m.loc[m["vote_type"] == "total", "lean"] = 0.0
    out = m[["fips", "vote_type", "expected", "lean", "share"]].fillna({"lean": 0.0}).reset_index(drop=True)
    return _measured_leans(state, out)


def _measured_leans(state: str, out: pd.DataFrame) -> pd.DataFrame:
    """Where a county has only a 'total' row (no 2022 breakdown, e.g. all of TX and MI) but its
    feed splits votes by type, use each type's 2024 lean and share instead
    (data/reference/vote_type_leans_2024.csv, measured from the counties' own 2024 files), so
    a mail-first count doesn't read as a Democratic swing."""
    lp = REF / "vote_type_leans_2024.csv"
    if not lp.exists():
        return out
    lv = pd.read_csv(lp, dtype={"fips": str})
    total_only = out.groupby("fips")["vote_type"].agg(lambda s: set(s) == {"total"})
    lv = lv[(lv["state"] == state) & lv["fips"].map(total_only).fillna(False).astype(bool)]
    if lv.empty:
        return out
    base = out[out["vote_type"] == "total"].set_index("fips")["expected"]
    split = lv.assign(expected=lv["fips"].map(base) * lv["share"])[["fips", "vote_type", "expected", "lean", "share"]]
    return pd.concat([out[~out["fips"].isin(lv["fips"])], split], ignore_index=True)
