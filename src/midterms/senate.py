"""2026 Senate: one table of every race from every source, and a simulation
of the election with an explicit polling-error model.

Error model (from 538's raw polls, 1998-2022, final-3-week averages of Senate
and governor polls vs results; see notebooks/01_polling_error):
- a national miss shared by every race: midterm SD 2.3pt (all even years 3.0),
  no reliable direction (midterm mean -0.3, D-minus-R);
- a race-specific miss whose SD shrinks with polling: 6.9pt with 1-2 polls,
  4.5 with 3-5, 4.2 with 6-10, 3.4 with 11+;
- a regional miss shared within a Census region: SD 1.1pt (1998-2022, after
  removing sampling noise);
- mildly fat tails (excess kurtosis ~0.8), so Student-t with 10 df.

Margins are Democratic (or the anti-Republican candidate, e.g. Osborn in
Nebraska) minus Republican, in points.
"""

from __future__ import annotations

import glob
import gzip
import io
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .snapshot import ROOT, SNAPSHOTS

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
NAME_TO_ABB = {v: k for k, v in STATES.items()}
REGION = {**{s: "Northeast" for s in "CT ME MA NH RI VT NJ NY PA".split()},
          **{s: "Midwest" for s in "IL IN MI OH WI IA KS MN MO NE ND SD".split()},
          **{s: "South" for s in "DE FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX".split()},
          **{s: "West" for s in "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()}}
SENATE_NOW = {"D": 47, "R": 53}  # Democrats incl. the two independents who caucus with them
VP_PARTY = "R"  # a 50-50 Senate goes to the Vice President's party
# The "fade": polls overstating candidates who run far ahead of their state's lean.
# First estimate (2026-10-29): -0.082 per point above the previous presidential margin,
# in-sample. Tested out of sample on 1998-2022 midterms (carryover.backtest, 2026-10-30)
# it didn't predict misses at all (leave-one-year-out error 5.57 vs 5.56 with no
# adjustment), so the main model leaves it out; LEAN_SLOPE_V1 keeps the old value for
# the "first version" variation.
LEAN_SLOPE = 0.0
LEAN_SLOPE_V1 = -0.082


def latest_snapshot() -> str:
    return sorted(glob.glob(str(SNAPSHOTS) + "/*/*/"))[-1]


def _gz(path: str):
    return gzip.open(path)


def _signed(pred: str) -> float:
    """'D+3.0' -> 3.0, 'R+1.7' -> -1.7."""
    side, val = pred.split("+")
    return float(val) * (1 if side == "D" else -1)


def races(snap: str | None = None, lean_slope: float | None = None) -> pd.DataFrame:
    snap = snap or latest_snapshot()
    # One row per race from Split Ticket; who holds the seat = its projected winner,
    # switched where it marks a flip. (DDHQ / The Hill supplied this before 2026-10-29;
    # its robots.txt disallows AI crawlers, so it was dropped.)
    st0 = pd.read_csv(_gz(snap + "split_ticket_senate_seats.csv.gz"))
    st0["state"] = st0["State"].map(NAME_TO_ABB)
    projected = np.where(st0["prediction"].map(_signed) > 0, "D", "R")
    flips = st0["flip"].astype(str).str.upper().eq("Y").to_numpy()
    df = pd.DataFrame({"state": st0["state"],
                       "held_by": np.where(flips, np.where(projected == "D", "R", "D"), projected)})
    df = df.dropna(subset=["state"]).groupby("state").first().reset_index()

    # Silver Bulletin polling average (latest day per race) and poll counts
    sb = pd.read_csv(_gz(snap + "silver_bulletin_averages.csv.gz"))
    sb = sb[sb["group"] == "Senate"].sort_values("date").groupby("id").tail(1)
    sb["state"] = sb["place"].map(NAME_TO_ABB)
    r_best = sb[["avg_R", "avg_R2", "avg_R3"]].max(axis=1)
    anti_r = sb[["avg_D", "avg_D2", "avg_I", "avg_I2"]].max(axis=1)
    sb["poll_margin"] = anti_r - r_best
    sb["poll_avg_date"] = sb["date"]
    polls = pd.read_csv(_gz(snap + "silver_bulletin_polls.csv.gz"))
    df = df.merge(sb.groupby("state")[["poll_margin", "poll_avg_date"]].last(), on="state", how="left")
    pid = next((c for c in polls.columns if c.lower() in ("id", "race_id", "race")), None)
    dcol = next((c for c in polls.columns if "end" in c.lower() and "date" in c.lower()), None) or \
        next((c for c in polls.columns if "date" in c.lower()), None)
    if pid and dcol:
        polls[dcol] = pd.to_datetime(polls[dcol], errors="coerce")
        recent = polls[polls[dcol] >= pd.Timestamp.today() - pd.Timedelta(days=30)]
        counts = recent[recent[pid].astype(str).str.contains("-S")].groupby(pid).size()
        ids = sb.set_index("id")["state"]
        df = df.merge(counts.rename("n_polls_30d").rename_axis("id").reset_index()
                      .assign(state=lambda d: d["id"].map(ids)).groupby("state")["n_polls_30d"].sum(),
                      on="state", how="left")
    df["n_polls_30d"] = df.get("n_polls_30d", pd.Series(np.nan, index=df.index)).fillna(0).astype(int)

    # Split Ticket
    st = pd.read_csv(_gz(snap + "split_ticket_senate_seats.csv.gz"))
    st["state"] = st["State"].map(NAME_TO_ABB)
    st["st_margin"] = st["prediction"].map(_signed)
    st["st_p_d"] = st["win_prob_d"] / 100
    df = df.merge(st.groupby("state")[["st_margin", "st_p_d"]].first(), on="state", how="left")

    # Polymarket: P(the non-Republican candidate wins)
    pm = pd.read_csv(snap + "polymarket.csv")
    pm = pm[pm["event"].str.contains("senate-election-winner", na=False)].copy()
    pm["state"] = pm["event"].str.replace(r"-senate-election-winner.*", "", regex=True).str.replace("-", " ").str.title() \
        .map(NAME_TO_ABB)
    # Some events (Alaska's ranked-choice race) don't label parties, so match the
    # Democratic / independent candidate by last name from Split Ticket's table.
    dem_last = st.groupby("state")["dem_name"].first().str.replace(r"\s*\(.*\)", "", regex=True) \
        .str.split().str[-1].str.lower()
    pm["dem_last"] = pm["state"].map(dem_last)
    hit = pm.apply(lambda r: isinstance(r["dem_last"], str) and r["dem_last"] in str(r["outcome"]).lower(), axis=1)
    pm_p = pm[hit].groupby("state")["yes_price"].sum().clip(upper=1).rename("pm_p_d")
    df = df.merge(pm_p, on="state", how="left")

    # state lean, and the polling average pulled toward it (see LEAN_SLOPE)
    lean = pd.read_csv(ROOT / "data" / "reference" / "pres_2024_by_state.csv").set_index("state")["d_margin_2024"]
    df["lean_2024"] = df["state"].map(lean)
    slope = LEAN_SLOPE if lean_slope is None else lean_slope
    df["poll_adj"] = df["poll_margin"] + slope * (df["poll_margin"] - df["lean_2024"])

    # where the 2024 presidential polls missed, relative to the national miss (see pres2024.py)
    miss_path = ROOT / "data" / "history" / "pres2024_state_miss.csv"
    if miss_path.exists():
        miss = pd.read_csv(miss_path).set_index("state")
        df["miss24_rel"] = df["state"].map(miss["miss_vs_national"])
        df["n_polls_2024"] = df["state"].map(miss["n"])
    df["blend"] = df[["poll_adj", "st_margin"]].mean(axis=1)
    return df.sort_values("st_p_d", ascending=False).reset_index(drop=True)


def with_carryover(df: pd.DataFrame, beta: float, base: str = "blend") -> pd.Series:
    """Center shifted by the expected carry-over of each state's 2024 polling miss."""
    return df[base] + beta * df.get("miss24_rel", pd.Series(0.0, index=df.index)).fillna(0.0)


@dataclass
class ErrorModel:
    """Margin error = national + state + race (+ optional regional), in points.

    Defaults follow docs/polling-error-research.md, from a three-way split of
    538's raw polls 1998-2022: national t(5) SD 3.0; state SD 2.7; race SD 2.7
    with 5+ pollsters, sqrt(2.5^2 + 25/n) with fewer. For a well-polled Senate
    race that adds to ~4.9, the measured miss. `ErrorModel.first_cut()` is the
    narrower version from the first pass (midterm-only national SD 2.3).
    """
    nat_sd: float = 3.0
    nat_df: int = 5
    nat_mean: float = 0.0        # + = Democrats beat their polls; run +-1.5 as scenarios
    state_sd: float = 2.7
    region_sd: float = 0.0
    race_floor_sd: float = 2.5
    race_df: int = 10
    well_polled: int = 5

    def race_sd(self, n_polls: np.ndarray) -> np.ndarray:
        n = np.asarray(n_polls, dtype=float)
        thin = np.sqrt(self.race_floor_sd ** 2 + 25.0 / np.maximum(n, 1))
        thin[n == 0] = 8.0
        race = np.where(n >= self.well_polled, 2.7, thin)
        return np.sqrt(race ** 2 + self.state_sd ** 2)  # one Senate race per state here, so state + race

    @classmethod
    def first_cut(cls) -> "ErrorModel":
        m = cls(nat_sd=2.3, nat_df=10, state_sd=0.0, region_sd=1.1)
        m.race_sd = lambda n: np.array([next(sd for cap, sd in ((2, 6.9), (5, 4.5), (10, 4.2), (10**6, 3.4)) if k <= cap)
                                        for k in np.asarray(n)])
        return m


def _t(rng, df, size):
    """Student-t scaled to unit variance."""
    return rng.standard_t(df, size) * np.sqrt((df - 2) / df)


def simulate(df: pd.DataFrame, center: str = "poll_margin", model: ErrorModel | None = None,
             n: int = 100_000, seed: int = 0) -> tuple[pd.DataFrame, dict]:
    """Monte Carlo of every race. `center` is the column used as each race's
    expected margin (falls back to Split Ticket's where it's missing)."""
    model = model or ErrorModel()
    rng = np.random.default_rng(seed)
    c = df[center].fillna(df["st_margin"]).to_numpy(float)
    sd = model.race_sd(df["n_polls_30d"].to_numpy())
    nat = model.nat_mean + model.nat_sd * _t(rng, model.nat_df, (n, 1))
    regions = df["state"].map(REGION).fillna("other").to_numpy()
    reg_draw = {r: model.region_sd * _t(rng, 10, (n, 1)) for r in set(regions)}
    reg = np.hstack([reg_draw[r] for r in regions])
    race = sd * _t(rng, model.race_df, (n, len(df)))
    margins = c + nat + reg + race
    d_win = margins > 0
    up_d = (df["held_by"] == "D").sum()
    d_not_up = SENATE_NOW["D"] - up_d
    seats = d_not_up + d_win.sum(axis=1)
    p_control = (seats >= 51).mean() if VP_PARTY == "R" else (seats >= 50).mean()
    out = df.assign(sim_p_d=d_win.mean(axis=0), race_sd=sd)
    summary = dict(p_d_control=p_control, mean_d_seats=seats.mean(),
                   seats_p10=np.percentile(seats, 10), seats_p90=np.percentile(seats, 90),
                   d_not_up=int(d_not_up), races=len(df))
    return out, summary
